"""Upgrade the database, safely adopting schemas created by legacy startup code."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.config import settings

logger = logging.getLogger(__name__)

LEGACY_HEAD = "f6b7c8d9e0a1"
MIGRATION_LOCK_ID = 0x504F5254464F4C49
LEGACY_SCHEMA_SENTINELS = {
    "accounts",
    "alerts",
    "holdings",
    "transactions",
    "analysis_history",
    "fx_rates",
    "market_prices",
    "news_articles",
    "strategies",
    "user_settings",
    "tax_calculations",
}


def classify_schema(tables: set[str]) -> str:
    if "alembic_version" in tables:
        return "versioned"
    present = tables & LEGACY_SCHEMA_SENTINELS
    if not present:
        return "empty"
    if present == LEGACY_SCHEMA_SENTINELS:
        return "legacy_complete"
    missing = ", ".join(sorted(LEGACY_SCHEMA_SENTINELS - present))
    raise RuntimeError(
        "Refusing to stamp a partial unversioned database; missing legacy tables: "
        + missing
    )


async def _schema_state(connection: AsyncConnection) -> str:
    tables = await connection.run_sync(
        lambda sync_connection: set(inspect(sync_connection).get_table_names())
    )
    return classify_schema(tables)


@asynccontextmanager
async def _postgres_migration_lock(
    connection: AsyncConnection,
) -> AsyncIterator[None]:
    await connection.execute(
        text("SELECT pg_advisory_lock(:lock_id)"),
        {"lock_id": MIGRATION_LOCK_ID},
    )
    try:
        yield
    finally:
        await connection.execute(
            text("SELECT pg_advisory_unlock(:lock_id)"),
            {"lock_id": MIGRATION_LOCK_ID},
        )


def _apply_migrations(state: str) -> None:
    config = Config("alembic.ini")
    if state == "legacy_complete":
        logger.warning(
            "Adopting complete unversioned legacy schema at revision %s",
            LEGACY_HEAD,
        )
        command.stamp(config, LEGACY_HEAD)
    command.upgrade(config, "head")


async def _migrate() -> None:
    engine = create_async_engine(settings.DATABASE_URL)
    try:
        if settings.is_sqlite:
            async with engine.connect() as connection:
                state = await _schema_state(connection)
            await asyncio.to_thread(_apply_migrations, state)
            return

        async with engine.connect() as connection:
            async with _postgres_migration_lock(connection):
                state = await _schema_state(connection)
                await asyncio.to_thread(_apply_migrations, state)
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(_migrate())


if __name__ == "__main__":
    main()
