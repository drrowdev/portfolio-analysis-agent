from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

engine_kwargs: dict = {"echo": False}
if not settings.is_sqlite:
    engine_kwargs["pool_size"] = 5
    engine_kwargs["max_overflow"] = 10

engine = create_async_engine(settings.DATABASE_URL, **engine_kwargs)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Apply legacy additive column guards after Alembic has initialized the schema."""
    from sqlalchemy import inspect, text

    async with engine.begin() as conn:
        # Legacy additive guards remain for columns introduced before every schema
        # change was represented in Alembic.
        migrations = [
            ("holdings", "price_change_pct", "NUMERIC"),
            ("holdings", "market_state", "VARCHAR(20)"),
            ("holdings", "extended_hours_price", "NUMERIC"),
            ("holdings", "extended_hours_change_pct", "NUMERIC"),
            ("holdings", "avg_cost_basis_native", "NUMERIC"),
            ("holdings", "total_cost_native", "NUMERIC"),
            ("holdings", "snapshot_date", "DATE"),
            ("tax_calculations", "declared_at", "TIMESTAMP"),
            ("tax_calculations", "paid_amount_eur", "VARCHAR(30)"),
            ("tax_calculations", "paid_date", "DATE"),
        ]
        for table, column, col_type in migrations:
            existing_columns = await conn.run_sync(
                lambda sync_conn, table_name=table: {
                    item["name"]
                    for item in inspect(sync_conn).get_columns(table_name)
                }
            )
            if column not in existing_columns:
                await conn.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
                )

        # Add new enum values for crypto support
        if not settings.is_sqlite:
            for enum_val in ["crypto"]:
                for enum_type in ["accounttype", "taxtreatment"]:
                    await conn.execute(
                        text(
                            f"ALTER TYPE {enum_type} "
                            f"ADD VALUE IF NOT EXISTS '{enum_val}'"
                        )
                    )
