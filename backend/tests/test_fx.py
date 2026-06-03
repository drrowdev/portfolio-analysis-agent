"""Tests for the USD->EUR FX conversion service (app.services.fx).

The conversion math (native / EURUSD) is the critical part — it directly
feeds the Finnish capital-gains cost basis. These tests use a lightweight
fake session and a monkeypatched rate fetch so no DB or network is touched.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.models.transaction import Transaction, TransactionType
from app.services import fx


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _FakeSession:
    """Minimal stand-in: returns preset rows for any execute()."""

    def __init__(self, rows):
        self._rows = rows

    async def execute(self, _stmt):
        return _FakeResult(self._rows)


def _tx(tx_type, d, price_native, total_native, currency="USD"):
    return Transaction(
        symbol="MSFT",
        currency=currency,
        transaction_type=tx_type,
        date=d,
        quantity=Decimal("1"),
        price_native=Decimal(price_native),
        total_native=Decimal(total_native),
        price_eur=Decimal(price_native),  # stored as USD pre-conversion
        total_eur=Decimal(total_native),
    )


@pytest.mark.asyncio
async def test_convert_uses_per_date_rate(monkeypatch):
    rows = [
        _tx(TransactionType.espp_purchase, date(2020, 1, 15), "108.00", "108.00"),
        _tx(TransactionType.espp_purchase, date(2021, 6, 30), "270.00", "270.00"),
    ]
    rates = {"2020-01-15": Decimal("1.08"), "2021-06-30": Decimal("1.20")}

    async def fake_fetch(dates, client=None):
        return {d: rates[d] for d in dates}

    monkeypatch.setattr(fx, "fetch_eurusd_rates", fake_fetch)

    summary = await fx.convert_symbol_to_eur(_FakeSession(rows), "MSFT")

    # 108 USD / 1.08 = 100 EUR ; 270 USD / 1.20 = 225 EUR
    assert rows[0].price_eur == Decimal("100.0000")
    assert rows[0].total_eur == Decimal("100.00")
    assert rows[0].fx_rate == Decimal("1.08")
    assert rows[1].price_eur == Decimal("225.0000")
    assert rows[1].fx_rate == Decimal("1.20")

    assert summary["transactions_updated"] == 2
    # cost basis: was 108+270=378 (USD-in-EUR) -> now 100+225=325 EUR
    assert summary["old_total_buy_eur"] == 378.0
    assert summary["new_total_buy_eur"] == 325.0
    assert summary["cost_basis_change_eur"] == pytest.approx(-53.0)


@pytest.mark.asyncio
async def test_convert_skips_rows_with_missing_rate(monkeypatch):
    rows = [
        _tx(TransactionType.espp_purchase, date(2020, 1, 15), "108.00", "108.00"),
        _tx(TransactionType.espp_purchase, date(2099, 1, 1), "200.00", "200.00"),
    ]

    async def fake_fetch(dates, client=None):
        return {"2020-01-15": Decimal("1.08"), "2099-01-01": None}

    monkeypatch.setattr(fx, "fetch_eurusd_rates", fake_fetch)

    summary = await fx.convert_symbol_to_eur(_FakeSession(rows), "MSFT")

    assert rows[0].price_eur == Decimal("100.0000")
    # Row with no rate is left untouched (still USD magnitude).
    assert rows[1].price_eur == Decimal("200.00")
    assert rows[1].fx_rate is None
    assert summary["transactions_updated"] == 1
    assert summary["dates_failed"] == 1


@pytest.mark.asyncio
async def test_convert_no_transactions_returns_zero(monkeypatch):
    async def fake_fetch(dates, client=None):  # pragma: no cover - shouldn't be called
        return {}

    monkeypatch.setattr(fx, "fetch_eurusd_rates", fake_fetch)

    summary = await fx.convert_symbol_to_eur(_FakeSession([]), "MSFT")
    assert summary["total_transactions"] == 0
    assert summary["transactions_updated"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
