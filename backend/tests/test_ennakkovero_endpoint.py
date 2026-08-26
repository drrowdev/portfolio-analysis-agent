"""End-to-end tests for the per-sale ennakkovero endpoint.

Covers the two behaviours that this app gets wrong most expensively:

1. **Scope.** Lots must come from the Fidelity ESPP account only. Pooling in
   MSFT held at Nordnet corrupts the FIFO cost basis and double-declares shares
   the broker already reports to Verohallinto.
2. **The OmaVero figures.** Updating the advance tax takes the *cumulative*
   year-to-date gain, not a per-sale figure, so the endpoint must publish both
   that cumulative number and the increase it should produce.
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest

pytest.importorskip("httpx")

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import get_db
from app.main import app
from app.models.account import Account, AccountType, TaxTreatment
from app.models.base import Base
from app.models.transaction import Transaction, TransactionType

ESPP = uuid.uuid4()
NORDNET = uuid.uuid4()


def _account(account_id, name, account_type, treatment, broker):
    return Account(
        id=account_id,
        name=name,
        broker=broker,
        account_type=account_type,
        external_id=name,
        currency="EUR",
        tax_treatment=treatment,
    )


def _txn(account_id, kind, d, qty, price):
    return Transaction(
        id=uuid.uuid4(),
        account_id=account_id,
        symbol="MSFT",
        isin="US5949181045",
        instrument_name="Microsoft Corp",
        currency="EUR",
        transaction_type=kind,
        date=d,
        quantity=Decimal(str(qty)),
        price_native=Decimal(str(price)),
        price_eur=Decimal(str(price)),
        total_native=Decimal(str(qty)) * Decimal(str(price)),
        total_eur=Decimal(str(qty)) * Decimal(str(price)),
        fees=Decimal("0"),
    )


async def _client(extra_txns=None):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async with maker() as db:
        db.add_all(
            [
                _account(ESPP, "Fidelity ESPP", AccountType.espp, TaxTreatment.espp, "fidelity"),
                _account(
                    NORDNET, "Nordnet AOT", AccountType.arvo_osuustili,
                    TaxTreatment.standard, "nordnet",
                ),
            ]
        )
        # ESPP lots: 100 shares at €50, bought well under 10 years ago.
        db.add(_txn(ESPP, TransactionType.espp_purchase, date(2020, 3, 2), 100, 50))
        for t in extra_txns or []:
            db.add(t)
        await db.commit()

    async def _override():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_db] = _override
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test"), maker


def _params(**over):
    p = {
        "symbol": "MSFT",
        "quantity": "50",
        "sell_price_eur": "150",
        "sell_date": "2026-05-04",
        "fees_eur": "0",
    }
    p.update(over)
    return p


@pytest.mark.asyncio
async def test_nordnet_lots_never_enter_the_espp_calculation():
    """A cheap Nordnet lot must not be consumed by an ESPP sale.

    Without account scoping, FIFO would take the older €5 Nordnet lot first and
    report a far larger gain than the ESPP position actually produced.
    """
    nordnet_lot = _txn(NORDNET, TransactionType.buy, date(2015, 1, 5), 100, 5)
    client, _ = await _client([nordnet_lot])
    async with client:
        r = await client.get("/api/v1/transactions/tax-calculation", params=_params())
    assert r.status_code == 200, r.text
    body = r.json()

    # 50 shares from the €50 ESPP lot: proceeds 7500, cost 2500, gain 5000.
    assert body["omavero"]["luovutushinta"] == pytest.approx(7500)
    assert body["omavero"]["luovutusvoitto"] == pytest.approx(5000)
    # Every consumed lot came from the ESPP purchase, not the 2015 Nordnet buy.
    assert all(lot["cost_per_share_eur"] == pytest.approx(50) for lot in body["lots_consumed"])
    assert body["coverage"]["shortfall_qty"] == 0
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_symbol_outside_the_espp_scope_is_rejected():
    client, _ = await _client()
    async with client:
        r = await client.get(
            "/api/v1/transactions/tax-calculation", params=_params(symbol="NOKIA")
        )
    assert r.status_code == 400
    assert "ESPP" in r.json()["detail"]
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_omavero_submission_reports_cumulative_year_figures():
    """The cumulative gain is what gets typed into OmaVero, not the sale's gain."""
    # An earlier ESPP sale in the same year: 20 shares at €120 -> gain 1400.
    earlier = _txn(ESPP, TransactionType.espp_sale, date(2026, 2, 10), 20, 120)
    client, _ = await _client([earlier])
    async with client:
        r = await client.get("/api/v1/transactions/tax-calculation", params=_params())
    assert r.status_code == 200, r.text
    body = r.json()
    sub = body["omavero_submission"]

    this_gain = body["omavero"]["luovutusvoitto"]
    assert this_gain == pytest.approx(5000)

    # Cumulative = earlier sale (2400 proceeds - 1000 cost = 1400) + this one.
    assert sub["cumulative_luovutusvoitot_eur"] == pytest.approx(1400 + 5000)
    assert sub["cumulative_luovutushinnat_eur"] == pytest.approx(2400 + 7500)
    assert sub["cumulative_hankintamenot_eur"] == pytest.approx(1000 + 2500)
    assert sub["sale_count"] == 2
    # This sale is hypothetical (not in the ledger), so it was added on top.
    assert sub["sale_is_recorded"] is False
    # The expected increase is this sale's own tax, not the cumulative tax.
    assert sub["expected_ennakkovero_increase_eur"] == pytest.approx(
        body["omavero"]["veron_maara"]
    )
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_recorded_sale_is_not_counted_twice():
    """When the sale already exists as a transaction it must not be added again."""
    recorded = _txn(ESPP, TransactionType.espp_sale, date(2026, 5, 4), 50, 150)
    client, _ = await _client([recorded])
    async with client:
        r = await client.get("/api/v1/transactions/tax-calculation", params=_params())
    assert r.status_code == 200, r.text
    sub = r.json()["omavero_submission"]

    assert sub["sale_is_recorded"] is True
    assert sub["sale_count"] == 1
    assert sub["cumulative_luovutusvoitot_eur"] == pytest.approx(5000)
    assert sub["cumulative_luovutushinnat_eur"] == pytest.approx(7500)
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_duplicate_same_day_sales_each_consume_their_own_lots():
    """Two identical sales on one day are two sales, not one.

    The skip that excludes "the sale being calculated" must fire once, not on
    every matching row — otherwise the other identical sale never consumes its
    FIFO lots and the reported gain is computed against the wrong cost basis.
    """
    # Second ESPP lot at a higher price so a mis-skipped lot is visible.
    second_lot = _txn(ESPP, TransactionType.espp_purchase, date(2021, 6, 1), 100, 80)
    first_sale = _txn(ESPP, TransactionType.espp_sale, date(2026, 5, 4), 50, 150)
    second_sale = _txn(ESPP, TransactionType.espp_sale, date(2026, 5, 4), 50, 150)
    client, _ = await _client([second_lot, first_sale, second_sale])
    async with client:
        r = await client.get("/api/v1/transactions/tax-calculation", params=_params())
    assert r.status_code == 200, r.text
    body = r.json()

    # One of the two identical sales is the one under calculation; the other
    # must have consumed the remaining 50 shares of the €50 lot, leaving this
    # sale to draw the last 50 of that lot... i.e. cost basis is still €50.
    # What must NOT happen is both being skipped, which would leave the €50 lot
    # untouched and silently understate the year's consumed basis.
    assert body["coverage"]["shortfall_qty"] == 0
    sub = body["omavero_submission"]
    # Both recorded sales are in the cumulative figure, and the sale under
    # calculation is not added a second time.
    assert sub["sale_count"] == 2
    assert sub["cumulative_luovutushinnat_eur"] == pytest.approx(15000)
    assert sub["sale_is_recorded"] is True
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_dividends_do_not_inflate_the_bracket():
    """Dividends go on the annual return, so they stay out of the advance tax.

    A large ESPP dividend must not push this sale into the 34 % band, because
    Verohallinto's ennakkovero basis is gains-only.
    """
    dividend = Transaction(
        id=uuid.uuid4(),
        account_id=ESPP,
        symbol="MSFT",
        isin="US5949181045",
        instrument_name="Microsoft Corp",
        currency="EUR",
        transaction_type=TransactionType.dividend,
        date=date(2026, 1, 15),
        quantity=Decimal("0"),
        price_native=Decimal("0"),
        price_eur=Decimal("0"),
        total_native=Decimal("40000"),
        total_eur=Decimal("40000"),
        fees=Decimal("0"),
    )
    client, _ = await _client([dividend])
    async with client:
        r = await client.get("/api/v1/transactions/tax-calculation", params=_params())
    assert r.status_code == 200, r.text
    bracket = r.json()["bracket"]

    assert bracket["prior_ytd_income_eur"] == pytest.approx(0)
    # Whole 5000 gain sits below the 30k threshold -> all at 30 %.
    assert bracket["amount_taxed_at_high_eur"] == pytest.approx(0)
    assert r.json()["omavero"]["veron_maara"] == pytest.approx(1500)
    app.dependency_overrides.clear()
