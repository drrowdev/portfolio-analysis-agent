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
    """Create all tables and add any missing columns."""
    from app.models import Base  # noqa: F811
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        # Lightweight migrations — add columns that create_all won't add to existing tables
        migrations = [
            ("holdings", "price_change_pct", "NUMERIC"),
            ("holdings", "market_state", "VARCHAR(20)"),
            ("holdings", "extended_hours_price", "NUMERIC"),
            ("holdings", "extended_hours_change_pct", "NUMERIC"),
        ]
        for table, column, col_type in migrations:
            await conn.execute(text(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {col_type}"
            ))

        # Add new enum values for crypto support
        for enum_val in ["crypto"]:
            for enum_type in ["accounttype", "taxtreatment"]:
                await conn.execute(text(
                    f"ALTER TYPE {enum_type} ADD VALUE IF NOT EXISTS '{enum_val}'"
                ))
