import logging
import uuid
from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.holding import Holding
from app.models.transaction import Transaction, TransactionType
from app.schemas.holding import HoldingRead
from app.services.market_data import update_holdings_prices

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/holdings", tags=["holdings"])


class QuickTradeRequest(BaseModel):
    account_id: uuid.UUID
    symbol: str
    instrument_name: str
    isin: str = ""
    currency: str = "EUR"
    exchange: str | None = None
    trade_type: str  # "buy" or "sell"
    quantity: Decimal
    price_per_share_eur: Decimal
    price_per_share_native: Decimal | None = None  # original price in trade currency
    fx_rate: Decimal | None = None  # USD/EUR rate used for conversion
    trade_date: date | None = None  # defaults to today
    fees: Decimal = Decimal("0")


@router.get("/", response_model=list[HoldingRead])
async def list_holdings(
    account_id: Optional[uuid.UUID] = None,
    db: AsyncSession = Depends(get_db),
) -> list[Holding]:
    """List holdings. Prices are refreshed by background scheduler (every 5-15 min)."""
    stmt = select(Holding)
    if account_id is not None:
        stmt = stmt.where(Holding.account_id == account_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/symbol-info")
async def symbol_info(symbol: str):
    """Look up instrument name for a ticker symbol via yfinance."""
    import asyncio
    import yfinance as yf
    from app.services.market_data import _yf_symbol

    yf_sym = _yf_symbol(symbol.upper())

    def _lookup():
        try:
            ticker = yf.Ticker(yf_sym)
            info = ticker.info or {}
            return info.get("longName") or info.get("shortName") or ""
        except Exception:
            return ""

    name = await asyncio.to_thread(_lookup)
    if not name:
        raise HTTPException(status_code=404, detail=f"Symbol '{symbol}' not found")
    return {"symbol": symbol.upper(), "name": name}


@router.get("/{account_id}", response_model=list[HoldingRead])
async def get_holdings_by_account(
    account_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> list[Holding]:
    result = await db.execute(
        select(Holding).where(Holding.account_id == account_id)
    )
    return list(result.scalars().all())


@router.post("/quick-trade")
async def quick_trade(trade: QuickTradeRequest, db: AsyncSession = Depends(get_db)):
    """Record a quick buy/sell trade, updating the holding accordingly."""
    stmt = select(Holding).where(
        Holding.account_id == trade.account_id,
        Holding.symbol == trade.symbol,
    )
    result = await db.execute(stmt)
    holding = result.scalar_one_or_none()

    if trade.trade_type == "buy":
        if holding:
            old_cost = holding.total_cost_eur
            old_qty = holding.total_quantity
            new_cost = trade.quantity * trade.price_per_share_eur
            holding.total_quantity = old_qty + trade.quantity
            holding.total_cost_eur = old_cost + new_cost
            holding.avg_cost_basis_eur = holding.total_cost_eur / holding.total_quantity
        else:
            total_cost = trade.quantity * trade.price_per_share_eur
            holding = Holding(
                account_id=trade.account_id,
                symbol=trade.symbol,
                instrument_name=trade.instrument_name,
                isin=trade.isin,
                currency=trade.currency,
                exchange=trade.exchange,
                total_quantity=trade.quantity,
                avg_cost_basis_eur=trade.price_per_share_eur,
                total_cost_eur=total_cost,
            )
            db.add(holding)
    elif trade.trade_type == "sell":
        if not holding:
            raise HTTPException(
                status_code=404,
                detail=f"No holding found for {trade.symbol} in this account",
            )
        if trade.quantity > holding.total_quantity:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot sell {trade.quantity} shares — only {holding.total_quantity} held",
            )
        # FIFO recalculation happens after transaction is recorded below
    else:
        raise HTTPException(status_code=400, detail="trade_type must be 'buy' or 'sell'")

    # Create a matching transaction record
    total_eur = trade.quantity * trade.price_per_share_eur
    price_native = trade.price_per_share_native or trade.price_per_share_eur
    total_native = trade.quantity * price_native
    tx_type = TransactionType.buy if trade.trade_type == "buy" else TransactionType.sell
    tx = Transaction(
        account_id=trade.account_id,
        symbol=trade.symbol,
        isin=trade.isin,
        instrument_name=trade.instrument_name,
        currency=trade.currency,
        transaction_type=tx_type,
        date=trade.trade_date or date.today(),
        quantity=trade.quantity,
        price_native=price_native,
        price_eur=trade.price_per_share_eur,
        total_native=total_native,
        total_eur=total_eur,
        fx_rate=trade.fx_rate,
        fees=trade.fees,
        notes=f"Quick trade: {trade.trade_type} {trade.quantity} {trade.symbol}",
    )
    db.add(tx)

    await db.commit()

    # For sells, recalculate holding using FIFO from all transactions
    if trade.trade_type == "sell":
        buy_types = [TransactionType.buy, TransactionType.espp_purchase]
        sell_types = [TransactionType.sell, TransactionType.espp_sale]
        tx_stmt = (
            select(Transaction)
            .where(Transaction.symbol == trade.symbol)
            .where(Transaction.transaction_type.in_(buy_types + sell_types))
            .order_by(Transaction.date.asc(), Transaction.created_at.asc())
        )
        tx_result = await db.execute(tx_stmt)
        all_txs = list(tx_result.scalars().all())
        running_qty, running_cost, _lots = _fifo_replay(all_txs, buy_types, sell_types)

        if running_qty > 0:
            holding.total_quantity = running_qty
            holding.total_cost_eur = running_cost
            holding.avg_cost_basis_eur = running_cost / running_qty
        else:
            await db.delete(holding)
        await db.commit()

    # Refresh prices for the updated holding
    try:
        await update_holdings_prices(db)
        await db.commit()
    except Exception:
        pass  # Price refresh is best-effort

    # Check if this sell requires Finnish tax filing (Fidelity ESPP stocks)
    tax_filing_required = (
        trade.trade_type == "sell"
        and trade.symbol in ("MSFT",)  # Add other ESPP symbols if needed
    )

    return {
        "status": "ok",
        "symbol": trade.symbol,
        "trade_type": trade.trade_type,
        "transaction_id": str(tx.id),
        "tax_filing_required": tax_filing_required,
    }


@router.delete("/{holding_id}")
async def delete_holding(holding_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Delete a holding entirely."""
    result = await db.execute(select(Holding).where(Holding.id == holding_id))
    holding = result.scalar_one_or_none()
    if not holding:
        raise HTTPException(status_code=404, detail="Holding not found")
    await db.delete(holding)
    await db.commit()
    return {"status": "deleted", "symbol": holding.symbol}


def _fifo_replay(transactions: list, buy_types: list, sell_types: list) -> tuple[Decimal, list]:
    """Replay transactions using FIFO and return (remaining_cost, remaining_lots).

    Each lot is [qty, price_eur_per_share].
    Returns the total cost of remaining lots and the lots themselves.
    """
    lots: list[list[Decimal]] = []  # [[qty, price_eur], ...]

    for tx in transactions:
        qty = tx.quantity or Decimal("0")
        if qty == 0:
            continue

        if tx.transaction_type in buy_types:
            price = tx.price_eur or (
                (tx.total_eur / qty) if tx.total_eur and qty else Decimal("0")
            )
            lots.append([qty, price])
        elif tx.transaction_type in sell_types:
            remaining = qty
            while remaining > 0 and lots:
                lot_qty, lot_price = lots[0]
                if lot_qty <= remaining:
                    remaining -= lot_qty
                    lots.pop(0)
                else:
                    lots[0] = [lot_qty - remaining, lot_price]
                    remaining = Decimal("0")

    running_qty = sum(lot[0] for lot in lots)
    running_cost = sum(lot[0] * lot[1] for lot in lots)
    return running_qty, running_cost, lots


@router.post("/recalculate/{symbol}")
async def recalculate_holding_cost(symbol: str, db: AsyncSession = Depends(get_db)):
    """Recalculate avg_cost_basis_eur and total_cost_eur by replaying all transactions for a symbol.

    Uses FIFO method: sells consume the oldest lots first, matching Fidelity/Finnish tax rules.
    """
    # Find the holding
    stmt = select(Holding).where(Holding.symbol == symbol)
    result = await db.execute(stmt)
    holding = result.scalar_one_or_none()
    if not holding:
        raise HTTPException(status_code=404, detail=f"No holding found for {symbol}")

    # Get all transactions for this symbol, ordered by date
    buy_types = [TransactionType.buy, TransactionType.espp_purchase]
    sell_types = [TransactionType.sell, TransactionType.espp_sale]
    tx_stmt = (
        select(Transaction)
        .where(Transaction.symbol == symbol)
        .where(Transaction.transaction_type.in_(buy_types + sell_types))
        .order_by(Transaction.date.asc(), Transaction.created_at.asc())
    )
    tx_result = await db.execute(tx_stmt)
    transactions = list(tx_result.scalars().all())

    # Replay using FIFO
    running_qty, running_cost, _lots = _fifo_replay(transactions, buy_types, sell_types)

    # Update the holding
    old_avg = holding.avg_cost_basis_eur
    old_total_cost = holding.total_cost_eur

    holding.total_quantity = running_qty
    holding.avg_cost_basis_eur = (running_cost / running_qty) if running_qty > 0 else Decimal("0")
    holding.total_cost_eur = running_cost

    await db.commit()

    # Refresh market prices so unrealized_pnl_eur is consistent with new cost
    await update_holdings_prices(db)
    await db.commit()
    await db.refresh(holding)

    return {
        "status": "recalculated",
        "symbol": symbol,
        "old_avg_cost_basis_eur": float(old_avg) if old_avg else None,
        "new_avg_cost_basis_eur": float(holding.avg_cost_basis_eur),
        "old_total_cost_eur": float(old_total_cost) if old_total_cost else None,
        "new_total_cost_eur": float(holding.total_cost_eur),
        "quantity": float(holding.total_quantity),
    }
