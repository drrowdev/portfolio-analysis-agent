import logging
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.account import Account, AccountType, TaxTreatment
from app.models.holding import Holding
from app.models.transaction import Transaction, TransactionType
from app.services import fx as fx_convert
from app.services.csv_parser import parse_fidelity_pdf, parse_nordnet_csv

router = APIRouter(prefix="/upload", tags=["upload"])

logger = logging.getLogger(__name__)

TAX_TREATMENT_MAP = {
    AccountType.arvo_osuustili: TaxTreatment.standard,
    AccountType.osakesaastotili: TaxTreatment.deferred,
    AccountType.espp: TaxTreatment.espp,
}

ACCOUNT_NAME_MAP = {
    AccountType.arvo_osuustili: "Nordnet AOT",
    AccountType.osakesaastotili: "Nordnet OST",
}

FIDELITY_TRANSACTION_TYPES = {
    "espp_purchase": TransactionType.espp_purchase,
    "dividend": TransactionType.dividend,
    "reinvestment": TransactionType.buy,
    "tax_withheld": TransactionType.withdrawal,
}


def _is_nordnet_lot_import(transaction: Transaction) -> bool:
    return bool(
        transaction.notes
        and transaction.notes.startswith("Imported from Nordnet lot export")
    )


def _fidelity_transaction_key(
    *,
    symbol: str,
    transaction_type: TransactionType,
    transaction_date,
    quantity: Decimal,
    price_native: Decimal,
    total_native: Decimal,
) -> tuple:
    return (
        symbol,
        transaction_type.value,
        transaction_date,
        quantity.normalize(),
        price_native.normalize(),
        total_native.normalize(),
    )


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
        old_txns = (
            await db.execute(
                select(Transaction).where(Transaction.account_id == account.id)
            )
        ).scalars().all()
        if any(not _is_nordnet_lot_import(transaction) for transaction in old_txns):
            raise HTTPException(
                status_code=409,
                detail=(
                    "This account contains transaction history beyond a prior open-lot "
                    "snapshot. Re-importing an open-lot export would erase that history, "
                    "so the existing ledger was left unchanged."
                ),
            )

        # A new open-lot snapshot may replace only an earlier open-lot snapshot.
        old_holdings = (
            await db.execute(select(Holding).where(Holding.account_id == account.id))
        ).scalars().all()
        latest_snapshot = account.last_holdings_snapshot_date or max(
            (
                holding.snapshot_date
                for holding in old_holdings
                if holding.snapshot_date is not None
            ),
            default=None,
        )
        if latest_snapshot is not None and result.report_date < latest_snapshot:
            raise HTTPException(
                status_code=409,
                detail=(
                    "This Nordnet snapshot is older than the latest imported "
                    "holdings snapshot, so the existing holdings were left unchanged."
                ),
            )
        for h in old_holdings:
            await db.delete(h)
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
            last_holdings_snapshot_date=result.report_date,
        )
        db.add(account)
        await db.flush()
    account.last_holdings_snapshot_date = result.report_date

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
            snapshot_date=result.report_date,
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
    preserved_transactions: list[Transaction] = []
    replace_holdings = True

    if existing:
        account = existing
        old_holdings = (
            await db.execute(select(Holding).where(Holding.account_id == account.id))
        ).scalars().all()
        old_txns = (
            await db.execute(
                select(Transaction).where(Transaction.account_id == account.id)
            )
        ).scalars().all()
        latest_snapshot = account.last_holdings_snapshot_date or max(
            (
                holding.snapshot_date
                for holding in old_holdings
                if holding.snapshot_date is not None
            ),
            default=None,
        )
        if account.last_holdings_snapshot_date is None:
            account.last_holdings_snapshot_date = latest_snapshot
        replace_holdings = (
            latest_snapshot is None or result.period_end >= latest_snapshot
        )
        if replace_holdings:
            for holding in old_holdings:
                await db.delete(holding)
            account.last_holdings_snapshot_date = result.period_end

        period_marker = f"({result.period_start} - {result.period_end})"
        for transaction in old_txns:
            if (
                transaction.notes
                and transaction.notes.startswith("Fidelity ")
                and transaction.notes.endswith(period_marker)
            ):
                await db.delete(transaction)
            else:
                preserved_transactions.append(transaction)
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
            last_holdings_snapshot_date=result.period_end,
        )
        db.add(account)
        await db.flush()

    # Replace holdings only with an equally recent or newer statement snapshot.
    holdings_created = 0
    for fh in result.holdings if replace_holdings else []:
        holding = Holding(
            id=uuid.uuid4(),
            account_id=account.id,
            symbol=fh.symbol,
            isin="US5949181045",  # MSFT ISIN
            instrument_name=fh.name,
            currency="USD",
            total_quantity=fh.quantity,
            snapshot_date=result.period_end,
            avg_cost_basis_eur=fh.cost_basis_usd / fh.quantity if fh.quantity else Decimal("0"),
            total_cost_eur=fh.cost_basis_usd,
            current_price_native=fh.price_usd,
            current_value_eur=fh.market_value_usd,  # stored as USD until FX conversion
            unrealized_pnl_eur=fh.unrealized_gain_usd,
        )
        db.add(holding)
        holdings_created += 1

    # Merge statement activity, replacing only the same statement period and
    # de-duplicating overlapping periods by native transaction identity.
    transactions_imported = 0
    duplicates_skipped = 0
    existing_keys = {
        _fidelity_transaction_key(
            symbol=transaction.symbol,
            transaction_type=transaction.transaction_type,
            transaction_date=transaction.date,
            quantity=transaction.quantity or Decimal("0"),
            price_native=transaction.price_native or Decimal("0"),
            total_native=transaction.total_native or Decimal("0"),
        )
        for transaction in preserved_transactions
    }
    for ft in result.transactions:
        tx_type = FIDELITY_TRANSACTION_TYPES.get(
            ft.transaction_type,
            TransactionType.buy,
        )
        quantity = ft.quantity or Decimal("0")
        price_native = ft.price_usd or Decimal("0")
        total_native = ft.amount_usd or quantity * price_native
        transaction_key = _fidelity_transaction_key(
            symbol=ft.symbol,
            transaction_type=tx_type,
            transaction_date=ft.date,
            quantity=quantity,
            price_native=price_native,
            total_native=total_native,
        )
        if transaction_key in existing_keys:
            duplicates_skipped += 1
            continue

        tx = Transaction(
            id=uuid.uuid4(),
            account_id=account.id,
            symbol=ft.symbol,
            isin="US5949181045",
            instrument_name=ft.name,
            currency="USD",
            transaction_type=tx_type,
            date=ft.date,
            quantity=quantity,
            price_native=price_native,
            price_eur=price_native,  # USD until FX conversion
            total_native=total_native,
            total_eur=total_native,
            fees=Decimal("0"),
            notes=f"Fidelity {ft.transaction_type} ({result.period_start} - {result.period_end})",
        )
        db.add(tx)
        existing_keys.add(transaction_key)
        transactions_imported += 1

    await db.flush()

    # Auto-convert USD figures to EUR using historical ECB rates so the data is
    # tax-ready immediately. Best-effort: if the FX API is unreachable the import
    # still succeeds and the user can re-run POST /transactions/fix-fx-rates/{symbol}.
    fx_conversion: dict | None = None
    fx_symbols = sorted({ft.symbol for ft in result.transactions if ft.symbol})
    try:
        converted = [await fx_convert.convert_symbol_to_eur(db, sym) for sym in fx_symbols]
        await db.flush()
        fx_conversion = {
            "ok": True,
            "symbols": [c for c in converted if c["total_transactions"]],
        }
    except Exception as exc:  # noqa: BLE001 - import must not fail on FX outage
        logger.warning("Auto FX conversion failed after Fidelity import: %s", exc)
        fx_conversion = {"ok": False, "error": str(exc)}

    return {
        "account_id": str(account.id),
        "holdings_created": holdings_created,
        "transactions_imported": transactions_imported,
        "duplicate_transactions_skipped": duplicates_skipped,
        "fx_conversion": fx_conversion,
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
