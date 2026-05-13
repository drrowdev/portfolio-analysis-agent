"""In-memory cache of symbol metadata loaded from the database on startup.

All lookups are synchronous against the cache; the cache is refreshed at
startup (and can be reloaded via `reload_cache`). This keeps hot paths
(price fetching, news matching, sector breakdowns) free of database round
trips while still allowing operators to manage symbol mappings via SQL or
a future admin endpoint.

If a symbol is not in the cache, accessors return None / sensible defaults
and callers fall back to using the local symbol directly.
"""

import logging
from typing import Optional

from sqlalchemy import select

from app.database import async_session_factory
from app.models.symbol_metadata import SymbolMetadata

logger = logging.getLogger(__name__)

_cache: dict[str, SymbolMetadata] = {}


async def reload_cache() -> int:
    """Reload the cache from the database. Returns the number of rows loaded."""
    async with async_session_factory() as db:
        result = await db.execute(select(SymbolMetadata))
        rows = list(result.scalars().all())

    _cache.clear()
    for row in rows:
        _cache[row.symbol] = row
    logger.info("Loaded %d symbol metadata rows into cache", len(rows))
    return len(rows)


def get(symbol: str) -> Optional[SymbolMetadata]:
    return _cache.get(symbol)


def yahoo_symbol(symbol: str) -> str:
    """Return the Yahoo Finance symbol for a local symbol, or the local symbol unchanged."""
    md = _cache.get(symbol)
    if md and md.yahoo_symbol:
        return md.yahoo_symbol
    return symbol


def finnhub_symbol(symbol: str) -> Optional[str]:
    """Return the Finnhub symbol for a local symbol, or None if not configured."""
    md = _cache.get(symbol)
    if md and md.finnhub_symbol:
        return md.finnhub_symbol
    return None


def company_name(symbol: str) -> str:
    """Return the company name for news queries; falls back to the local symbol."""
    md = _cache.get(symbol)
    if md and md.company_name:
        return md.company_name
    return symbol


def isin(symbol: str) -> Optional[str]:
    md = _cache.get(symbol)
    return md.isin if md else None


def news_keywords(symbol: str) -> list[str]:
    md = _cache.get(symbol)
    if md and md.news_keywords:
        return md.news_keywords
    return []


def sector_info(symbol: str) -> Optional[dict[str, str]]:
    """Return {sector, industry, country} for a symbol if available."""
    md = _cache.get(symbol)
    if not md:
        return None
    if not (md.sector or md.industry or md.country):
        return None
    return {
        "sector": md.sector or "Other",
        "industry": md.industry or "Unknown",
        "country": md.country or "Unknown",
    }


def has_finnhub(symbol: str) -> bool:
    md = _cache.get(symbol)
    return bool(md and md.has_finnhub_news)


def has_yahoo(symbol: str) -> bool:
    md = _cache.get(symbol)
    return bool(md and md.has_yahoo_news)


def skip_in_aggregations(symbol: str) -> bool:
    md = _cache.get(symbol)
    return bool(md and md.skip_in_aggregations)


def all_symbols() -> list[str]:
    return list(_cache.keys())


def reverse_finnhub_map() -> dict[str, str]:
    """Map Finnhub symbol -> local symbol (used for matching API responses back to portfolio symbols)."""
    out: dict[str, str] = {}
    for sym, md in _cache.items():
        if md.finnhub_symbol:
            out[md.finnhub_symbol] = sym
    return out
