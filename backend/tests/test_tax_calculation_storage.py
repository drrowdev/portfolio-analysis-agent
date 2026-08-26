"""Tests for saving and summarising ennakkovero calculations.

The engine-version warning tells the user to re-open and re-save an old
calculation. That instruction must not destroy the very record it protects: the
declaration status and any payment amount they typed.
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

ESPP = uuid.uuid4()

CALC = {
    "omavero": {
        "luovutushinta": 7500.0,
        "hankintameno_kaytetty": 2500.0,
        "luovutusvoitto": 5000.0,
        "veron_maara": 1500.0,
    }
}

PAYLOAD = {
    "symbol": "MSFT",
    "sell_date": "2026-05-04",
    "quantity_sold": "50",
    "sell_price_eur": "150",
    "fees_eur": "0",
    "calculation_json": CALC,
}


async def _client(with_espp_account=True):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    if with_espp_account:
        async with maker() as db:
            db.add(
                Account(
                    id=ESPP,
                    name="Fidelity ESPP",
                    broker="fidelity",
                    account_type=AccountType.espp,
                    external_id="espp",
                    currency="USD",
                    tax_treatment=TaxTreatment.espp,
                )
            )
            await db.commit()

    async def _override():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_db] = _override
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_resaving_preserves_declaration_and_payment():
    """Re-saving after an engine correction must not un-declare the sale."""
    client = await _client()
    async with client:
        base = "/api/v1/transactions/tax-calculations/"
        created = (await client.post(base, json=PAYLOAD)).json()
        calc_id = created["id"]
        assert created["engine_version"] is not None
        assert created["is_legacy"] is False

        # The user declares it and records what they actually paid.
        marked = await client.patch(
            f"{base}{calc_id}/declaration",
            json={"declared": True, "paid_amount_eur": "1650.00", "paid_date": "2026-06-08"},
        )
        assert marked.status_code == 200, marked.text
        assert marked.json()["declared"] is True

        # A corrected engine produces a different figure; the user re-saves.
        corrected = dict(PAYLOAD)
        corrected["calculation_json"] = {
            "omavero": {**CALC["omavero"], "veron_maara": 1400.0}
        }
        resaved = (await client.post(base, json=corrected)).json()

        assert resaved["declared"] is True, "re-saving un-declared the sale"
        assert resaved["paid_amount_eur"] == "1650.00", "re-saving discarded the payment"
        assert str(resaved["paid_date"]) == "2026-06-08"
        assert resaved["calculation_json"]["omavero"]["veron_maara"] == 1400.0

        # And the summary still sees exactly one declared, paid sale.
        summary = (await client.get(f"{base}declaration-summary?year=2026")).json()
        assert summary["sale_count"] == 1
        assert summary["declared_count"] == 1
        assert summary["paid_count"] == 1
        assert summary["total_paid_eur"] == "1650.00"
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_summary_fails_closed_without_an_espp_account():
    """No ESPP account means no ESPP sales — never fall back to every MSFT row."""
    client = await _client(with_espp_account=False)
    async with client:
        base = "/api/v1/transactions/tax-calculations/"
        assert (await client.post(base, json=PAYLOAD)).status_code == 201

        summary = (await client.get(f"{base}declaration-summary?year=2026")).json()
        assert summary["sale_count"] == 0
        assert summary["total_tax_eur"] == "0.00"
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_summary_reports_engine_provenance():
    client = await _client()
    async with client:
        base = "/api/v1/transactions/tax-calculations/"
        await client.post(base, json=PAYLOAD)
        summary = (await client.get(f"{base}declaration-summary?year=2026")).json()

        assert summary["legacy_count"] == 0
        assert summary["sales"][0]["is_legacy"] is False
        assert summary["sales"][0]["engine_version"] is not None
        # And no payable balance is published.
        assert "remaining_to_pay_eur" not in summary
        assert "over_under_eur" not in summary
    app.dependency_overrides.clear()
