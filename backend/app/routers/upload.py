import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.account import Account, AccountType, TaxTreatment
from app.models.holding import Holding
from app.models.transaction import Transaction, TransactionType
from app.services.csv_parser import parse_fidelity_pdf, parse_nordnet_csv

router = APIRouter(prefix="/upload", tags=["upload"])

TAX_TREATMENT_MAP = {
    AccountType.arvo_osuustili: TaxTreatment.standard,
    AccountType.osakesaastotili: TaxTreatment.deferred,
    AccountType.espp: TaxTreatment.espp,
}

ACCOUNT_NAME_MAP = {
    AccountType.arvo_osuustili: "Nordnet AOT",
    AccountType.osakesaastotili: "Nordnet OST",
}


@router.post("/nordnet")
async def upload_nordnet_csv(
    file: UploadFile,
    account_type: str = Form(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Upload a Nordnet CSV export (ostoerittäin format) for parsing."""
    content = await file.read()

    try:
        acct_type = AccountType(account_type)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid account_type: {account_type}. Must be one of: arvo_osuustili, osakesaastotili",
        )

    result = await parse_nordnet_csv(content)

    # Find or create account
    stmt = select(Account).where(
        Account.external_id == result.portfolio_id,
        Account.account_type == acct_type,
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()

    if existing:
        account = existing
        # Delete old holdings and transactions for re-import
        old_holdings = (
            await db.execute(select(Holding).where(Holding.account_id == account.id))
        ).scalars().all()
        for h in old_holdings:
            await db.delete(h)
        old_txns = (
            await db.execute(
                select(Transaction).where(Transaction.account_id == account.id)
            )
        ).scalars().all()
        for t in old_txns:
            await db.delete(t)
        await db.flush()
    else:
        account = Account(
            id=uuid.uuid4(),
            name=ACCOUNT_NAME_MAP.get(acct_type, f"Nordnet {account_type}"),
            broker="nordnet",
            account_type=acct_type,
            external_id=result.portfolio_id,
            currency="EUR",
            tax_treatment=TAX_TREATMENT_MAP[acct_type],
        )
        db.add(account)
        await db.flush()

    # Create transactions from lots
    for lot in result.lots:
        tx = Transaction(
            id=uuid.uuid4(),
            account_id=account.id,
            symbol=lot.ticker,
            isin=lot.isin,
            instrument_name=lot.instrument_name,
            currency=lot.currency,
            transaction_type=TransactionType.buy,
            date=lot.purchase_date,
            quantity=lot.quantity,
            price_native=lot.cost_price_native,
            price_eur=lot.cost_price_eur,
            total_native=lot.cost_value_native,
            total_eur=lot.cost_value_eur,
            fx_rate=(
                (lot.cost_price_eur / lot.cost_price_native)
                if lot.cost_price_native and lot.currency != "EUR"
                else None
            ),
            fees=Decimal("0"),
            notes=f"Imported from Nordnet lot export ({result.report_date})",
        )
        db.add(tx)

    # Create holdings from aggregated summary
    holdings_created = 0
    for hs in result.holdings_summary:
        holding = Holding(
            id=uuid.uuid4(),
            account_id=account.id,
            symbol=hs["ticker"],
            isin=hs["isin"],
            instrument_name=hs["instrument_name"],
            currency=hs["currency"],
            total_quantity=hs["total_quantity"],
            avg_cost_basis_eur=hs["avg_cost_basis_eur"],
            total_cost_eur=hs["total_cost_eur"],
            current_value_eur=hs["total_market_value_eur"],
            unrealized_pnl_eur=hs["unrealized_pnl_eur"],
            unrealized_pnl_pct=hs["unrealized_pnl_pct"],
        )
        db.add(holding)
        holdings_created += 1

    await db.flush()

    return {
        "account_id": str(account.id),
        "lots_imported": len(result.lots),
        "holdings_created": holdings_created,
        "summary": {
            "portfolio_id": result.portfolio_id,
            "report_date": str(result.report_date),
            "account_type": account_type,
            "holdings": [
                {
                    "symbol": h["ticker"],
                    "name": h["instrument_name"],
                    "quantity": str(h["total_quantity"]),
                    "cost_eur": str(h["total_cost_eur"]),
                    "market_value_eur": str(h["total_market_value_eur"]),
                    "pnl_eur": str(h["unrealized_pnl_eur"]),
                    "pnl_pct": str(h["unrealized_pnl_pct"]),
                }
                for h in result.holdings_summary
            ],
        },
    }


@router.post("/fidelity")
async def upload_fidelity_pdf(
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Upload a Fidelity Stock Plan statement PDF for parsing."""
    content = await file.read()

    result = await parse_fidelity_pdf(content)

    # Find or create account
    external_id = result.participant_number or "fidelity-espp"
    stmt = select(Account).where(
        Account.external_id == external_id,
        Account.account_type == AccountType.espp,
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()

    if existing:
        account = existing
        # Delete old holdings and transactions for re-import
        old_holdings = (
            await db.execute(select(Holding).where(Holding.account_id == account.id))
        ).scalars().all()
        for h in old_holdings:
            await db.delete(h)
        old_txns = (
            await db.execute(
                select(Transaction).where(Transaction.account_id == account.id)
            )
        ).scalars().all()
        for t in old_txns:
            await db.delete(t)
        await db.flush()
    else:
        account = Account(
            id=uuid.uuid4(),
            name="Fidelity ESPP",
            broker="fidelity",
            account_type=AccountType.espp,
            external_id=external_id,
            currency="USD",
            tax_treatment=TaxTreatment.espp,
        )
        db.add(account)
        await db.flush()

    # Create holdings
    holdings_created = 0
    for fh in result.holdings:
        holding = Holding(
            id=uuid.uuid4(),
            account_id=account.id,
            symbol=fh.symbol,
            isin="US5949181045",  # MSFT ISIN
            instrument_name=fh.name,
            currency="USD",
            total_quantity=fh.quantity,
            avg_cost_basis_eur=fh.cost_basis_usd / fh.quantity if fh.quantity else Decimal("0"),
            total_cost_eur=fh.cost_basis_usd,
            current_price_native=fh.price_usd,
            current_value_eur=fh.market_value_usd,  # stored as USD until FX conversion
            unrealized_pnl_eur=fh.unrealized_gain_usd,
        )
        db.add(holding)
        holdings_created += 1

    # Create transactions
    transactions_imported = 0
    for ft in result.transactions:
        tx_type_map = {
            "espp_purchase": TransactionType.espp_purchase,
            "dividend": TransactionType.dividend,
            "reinvestment": TransactionType.buy,
            "tax_withheld": TransactionType.withdrawal,
        }
        tx_type = tx_type_map.get(ft.transaction_type, TransactionType.buy)

        tx = Transaction(
            id=uuid.uuid4(),
            account_id=account.id,
            symbol=ft.symbol,
            isin="US5949181045",
            instrument_name=ft.name,
            currency="USD",
            transaction_type=tx_type,
            date=ft.date,
            quantity=ft.quantity or Decimal("0"),
            price_native=ft.price_usd or Decimal("0"),
            price_eur=ft.price_usd or Decimal("0"),  # USD until FX conversion
            total_native=ft.amount_usd or (
                (ft.quantity or Decimal("0")) * (ft.price_usd or Decimal("0"))
            ),
            total_eur=ft.amount_usd or (
                (ft.quantity or Decimal("0")) * (ft.price_usd or Decimal("0"))
            ),
            fees=Decimal("0"),
            notes=f"Fidelity {ft.transaction_type} ({result.period_start} - {result.period_end})",
        )
        db.add(tx)
        transactions_imported += 1

    await db.flush()

    return {
        "account_id": str(account.id),
        "holdings_created": holdings_created,
        "transactions_imported": transactions_imported,
        "summary": {
            "participant_number": result.participant_number,
            "period": f"{result.period_start} to {result.period_end}",
            "account_value_usd": str(result.account_value_usd),
            "holdings": [
                {
                    "symbol": h.symbol,
                    "name": h.name,
                    "quantity": str(h.quantity),
                    "price_usd": str(h.price_usd),
                    "market_value_usd": str(h.market_value_usd),
                    "cost_basis_usd": str(h.cost_basis_usd),
                    "unrealized_gain_usd": str(h.unrealized_gain_usd),
                }
                for h in result.holdings
            ],
            "transactions_count": transactions_imported,
            "espp_contribution_rate": str(result.espp_contribution_rate_pct),
        },
    }
