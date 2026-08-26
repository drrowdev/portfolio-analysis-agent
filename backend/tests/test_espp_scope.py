"""Tests for the ESPP scope guard.

The tracker exists only for MSFT held in the Fidelity ESPP account. Selecting
lots by symbol alone previously pooled in any MSFT held at Nordnet, which both
corrupts the FIFO cost basis and double-declares shares the broker already
reports to Verohallinto. These tests pin the guard that prevents that.
"""

import uuid

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.models.account import Account, AccountType, TaxTreatment
from app.models.base import Base
from app.services import espp_scope


async def _session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    return maker()


def _account(name: str, account_type: AccountType, treatment: TaxTreatment) -> Account:
    return Account(
        id=uuid.uuid4(),
        name=name,
        broker="fidelity" if account_type is AccountType.espp else "nordnet",
        account_type=account_type,
        external_id=name,
        currency="USD" if account_type is AccountType.espp else "EUR",
        tax_treatment=treatment,
    )


@pytest.mark.asyncio
async def test_only_the_espp_account_is_in_scope():
    db = await _session()
    espp = _account("Fidelity ESPP", AccountType.espp, TaxTreatment.espp)
    aot = _account("Nordnet AOT", AccountType.arvo_osuustili, TaxTreatment.standard)
    ost = _account("Nordnet OST", AccountType.osakesaastotili, TaxTreatment.deferred)
    db.add_all([espp, aot, ost])
    await db.commit()

    ids = await espp_scope.espp_account_ids(db)
    assert ids == [espp.id]
    assert aot.id not in ids
    assert ost.id not in ids
    await db.close()


@pytest.mark.asyncio
async def test_require_scope_returns_espp_account_for_msft():
    db = await _session()
    espp = _account("Fidelity ESPP", AccountType.espp, TaxTreatment.espp)
    db.add(espp)
    await db.commit()

    assert await espp_scope.require_espp_scope(db, "MSFT") == [espp.id]
    # Case-insensitive on the symbol.
    assert await espp_scope.require_espp_scope(db, "msft") == [espp.id]
    await db.close()


@pytest.mark.asyncio
async def test_require_scope_rejects_other_symbols():
    """Nordnet holdings are broker-reported and must never be declared here."""
    db = await _session()
    db.add(_account("Fidelity ESPP", AccountType.espp, TaxTreatment.espp))
    await db.commit()

    with pytest.raises(espp_scope.EsppScopeError):
        await espp_scope.require_espp_scope(db, "NOKIA")
    await db.close()


@pytest.mark.asyncio
async def test_require_scope_fails_loudly_without_an_espp_account():
    """Better to refuse than to silently compute over the wrong shares."""
    db = await _session()
    db.add(_account("Nordnet AOT", AccountType.arvo_osuustili, TaxTreatment.standard))
    await db.commit()

    with pytest.raises(espp_scope.EsppScopeError):
        await espp_scope.require_espp_scope(db, "MSFT")
    await db.close()
