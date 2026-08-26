"""The single source of truth for what this app's ennakkovero engine covers.

This tracker exists for exactly one purpose: computing Finnish advance tax
(ennakkovero) on sales of MSFT shares held in the Fidelity **ESPP** account.
Everything held at Nordnet is reported to Verohallinto by the broker itself and
must never appear in these calculations — including MSFT bought at Nordnet.

Selecting lots by symbol alone is therefore not safe: it would pool ESPP lots
with Nordnet lots into one FIFO chain, corrupting the cost basis *and*
double-declaring shares the broker already reports. Every capital-gains query in
this app must be scoped through :func:`espp_account_ids`.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account, AccountType

#: The only instrument this tracker declares. Deliberately hard-coded.
ESPP_SYMBOL = "MSFT"


class EsppScopeError(RuntimeError):
    """Raised when a calculation is attempted outside the ESPP scope."""


async def espp_account_ids(db: AsyncSession) -> list[uuid.UUID]:
    """Account ids that hold the ESPP position.

    Identified by ``account_type == espp`` rather than by broker name so a
    renamed or re-imported Fidelity account keeps working. Returned as UUIDs so
    they can be used directly in ``Transaction.account_id.in_(...)`` — the column
    is a UUID type and comparing it against strings raises at query time.
    """
    result = await db.execute(
        select(Account.id).where(Account.account_type == AccountType.espp)
    )
    return list(result.scalars().all())


async def require_espp_scope(db: AsyncSession, symbol: str) -> list[uuid.UUID]:
    """Return the ESPP account ids, rejecting anything outside the scope.

    Raises :class:`EsppScopeError` if the symbol is not the ESPP instrument or
    if no ESPP account exists — better to fail loudly than to silently compute
    an advance tax over the wrong set of shares.
    """
    if symbol.upper() != ESPP_SYMBOL:
        raise EsppScopeError(
            f"This tracker only covers {ESPP_SYMBOL} in the Fidelity ESPP account. "
            f"Sales of {symbol} are reported by the broker and must not be declared here."
        )
    account_ids = await espp_account_ids(db)
    if not account_ids:
        raise EsppScopeError(
            "No ESPP account found. Import a Fidelity statement before calculating "
            "advance tax."
        )
    return account_ids
