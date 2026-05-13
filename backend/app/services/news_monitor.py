"""News monitoring service — polls multiple sources for portfolio-relevant news."""

import asyncio
import logging
import uuid
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.holding import Holding
from app.models.news import NewsArticle
from app.services import symbol_metadata

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = 15.0

# ---------------------------------------------------------------------------
# Simple keyword-based sentiment
# ---------------------------------------------------------------------------

POSITIVE_WORDS = [
    "surge", "jump", "beat", "growth", "profit", "upgrade", "record",
    "strong", "bullish", "rally", "gain", "outperform", "breakout", "soar",
    "exceed", "positive", "buy", "raise", "boost", "optimistic",
]

NEGATIVE_WORDS = [
    "crash", "drop", "fall", "loss", "miss", "downgrade", "cut", "weak",
    "bearish", "plunge", "layoff", "decline", "sell", "warning", "risk",
    "negative", "slump", "fraud", "recall", "lawsuit",
]


def simple_sentiment(title: str, summary: str | None) -> float:
    """Quick keyword-based sentiment score (-1 to 1)."""
    text = (title + " " + (summary or "")).lower()
    pos = sum(1 for w in POSITIVE_WORDS if w in text)
    neg = sum(1 for w in NEGATIVE_WORDS if w in text)
    total = pos + neg
    if total == 0:
        return 0.0
    return round((pos - neg) / total, 2)


# ---------------------------------------------------------------------------
# Source: NewsAPI
# ---------------------------------------------------------------------------

async def fetch_newsapi(symbols: list[str], api_key: str) -> list[dict]:
    """Fetch news from NewsAPI for given symbols."""
    if not api_key:
        logger.debug("NewsAPI key not configured — skipping")
        return []

    queries = [symbol_metadata.company_name(s) for s in symbols]
    query_str = " OR ".join(f'"{q}"' for q in queries)

    from_date = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%d")

    url = "https://newsapi.org/v2/everything"
    params = {
        "q": query_str,
        "from": from_date,
        "sortBy": "publishedAt",
        "language": "en",
        "pageSize": 50,
        "apiKey": api_key,
    }

    articles: list[dict] = []
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        for art in data.get("articles", []):
            # Determine which symbol(s) this article relates to
            matched_symbol = _match_symbol(art.get("title", ""), art.get("description", ""), symbols)
            published = _parse_iso(art.get("publishedAt"))
            articles.append({
                "symbol": matched_symbol,
                "title": art.get("title", "")[:500],
                "summary": (art.get("description") or "")[:2000] or None,
                "url": art.get("url", ""),
                "source": (art.get("source") or {}).get("name", "NewsAPI"),
                "published_at": published,
            })
    except httpx.HTTPStatusError as exc:
        logger.warning("NewsAPI HTTP error %s: %s", exc.response.status_code, exc.response.text[:200])
    except Exception:
        logger.exception("NewsAPI fetch failed")

    return articles


def _match_symbol(title: str, description: str | None, symbols: list[str]) -> str | None:
    """Return the first symbol whose company name, ticker, or keywords appear in the text."""
    text = (title + " " + (description or "")).lower()
    for sym in symbols:
        # Check primary query name
        query = symbol_metadata.company_name(sym).lower()
        if query in text or sym.lower() in text:
            return sym
        # Check additional keywords
        for kw in symbol_metadata.news_keywords(sym):
            if kw in text:
                return sym
    return None


# ---------------------------------------------------------------------------
# Source: Finnhub
# ---------------------------------------------------------------------------

async def fetch_finnhub_news(symbol: str, api_key: str, days_back: int = 3) -> list[dict]:
    """Fetch company news from Finnhub for a symbol."""
    if not api_key:
        logger.debug("Finnhub API key not configured — skipping")
        return []

    # Map portfolio symbol to Finnhub symbol (Nordic stocks need exchange suffix)
    finnhub_sym = symbol_metadata.finnhub_symbol(symbol) or symbol
    if not symbol_metadata.has_finnhub(symbol) and symbol_metadata.finnhub_symbol(symbol) is None:
        return []

    today = date.today()
    from_date = (today - timedelta(days=days_back)).isoformat()
    to_date = today.isoformat()

    url = "https://finnhub.io/api/v1/company-news"
    params = {
        "symbol": finnhub_sym,
        "from": from_date,
        "to": to_date,
        "token": api_key,
    }

    articles: list[dict] = []
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        for item in data[:20]:  # cap per symbol
            published = datetime.fromtimestamp(item.get("datetime", 0), tz=timezone.utc)
            articles.append({
                "symbol": symbol,
                "title": (item.get("headline") or "")[:500],
                "summary": (item.get("summary") or "")[:2000] or None,
                "url": item.get("url", ""),
                "source": item.get("source", "Finnhub"),
                "published_at": published,
            })
    except httpx.HTTPStatusError as exc:
        logger.warning("Finnhub HTTP error for %s: %s", symbol, exc.response.status_code)
    except Exception:
        logger.exception("Finnhub fetch failed for %s", symbol)

    return articles


async def fetch_finnhub_all(symbols: list[str], api_key: str) -> list[dict]:
    """Fetch Finnhub news for all eligible symbols concurrently."""
    if not api_key:
        return []
    eligible = [
        s for s in symbols
        if symbol_metadata.has_finnhub(s) or symbol_metadata.finnhub_symbol(s) is not None
    ]
    tasks = [fetch_finnhub_news(s, api_key) for s in eligible]
    if not tasks:
        return []
    results = await asyncio.gather(*tasks, return_exceptions=True)
    articles: list[dict] = []
    for r in results:
        if isinstance(r, list):
            articles.extend(r)
        elif isinstance(r, Exception):
            logger.warning("Finnhub gather error: %s", r)
    return articles


async def fetch_earnings_calendar(api_key: str, days_ahead: int = 90) -> list[dict]:
    """Fetch upcoming earnings dates for portfolio companies from Finnhub."""
    if not api_key:
        logger.debug("Finnhub API key not configured — skipping earnings")
        return []

    today = date.today()
    to_date = (today + timedelta(days=days_ahead)).isoformat()

    url = "https://finnhub.io/api/v1/calendar/earnings"
    params = {
        "from": today.isoformat(),
        "to": to_date,
        "token": api_key,
    }

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        portfolio_syms = set(symbol_metadata.all_symbols())
        # Reverse map: Finnhub symbol → portfolio symbol
        reverse_map = symbol_metadata.reverse_finnhub_map()
        earnings: list[dict] = []
        for item in data.get("earningsCalendar", []):
            sym = item.get("symbol", "")
            # Match against portfolio symbols or Finnhub-mapped symbols
            display_sym = sym
            if sym in portfolio_syms:
                display_sym = sym
            elif sym in reverse_map:
                display_sym = reverse_map[sym]
            else:
                continue
            earnings.append({
                "symbol": display_sym,
                "date": item.get("date"),
                "estimate_eps": item.get("epsEstimate"),
                "actual_eps": item.get("epsActual"),
                "revenue_estimate": item.get("revenueEstimate"),
                "quarter": item.get("quarter"),
                "year": item.get("year"),
            })
        return sorted(earnings, key=lambda e: e.get("date") or "9999")
    except Exception:
        logger.exception("Finnhub earnings calendar fetch failed")
        return []


# ---------------------------------------------------------------------------
# Source: Yahoo Finance RSS
# ---------------------------------------------------------------------------

async def fetch_yahoo_rss(symbol: str) -> list[dict]:
    """Fetch news from Yahoo Finance RSS feed for a single symbol.
    
    NOTE: The old RSS endpoint is deprecated and returns 404.
    We use the v1 RSS feed URL instead.
    """
    if not symbol_metadata.has_yahoo(symbol):
        return []

    url = f"https://finance.yahoo.com/rss/headline?s={symbol}"
    articles: list[dict] = []

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return []  # silently skip if Yahoo RSS is unavailable

        root = ET.fromstring(resp.text)
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "")[:500]
            link = item.findtext("link") or ""
            pub_date_str = item.findtext("pubDate") or ""
            description = (item.findtext("description") or "")[:2000] or None

            published = _parse_rss_date(pub_date_str)
            articles.append({
                "symbol": symbol,
                "title": title,
                "summary": description,
                "url": link,
                "source": "Yahoo Finance",
                "published_at": published,
            })
    except Exception:
        pass  # Yahoo RSS is best-effort; Finnhub is the primary source

    return articles


async def fetch_yahoo_all(symbols: list[str]) -> list[dict]:
    """Fetch Yahoo RSS news for all eligible symbols concurrently."""
    tasks = [fetch_yahoo_rss(s) for s in symbols if symbol_metadata.has_yahoo(s)]
    if not tasks:
        return []
    results = await asyncio.gather(*tasks, return_exceptions=True)
    articles: list[dict] = []
    for r in results:
        if isinstance(r, list):
            articles.extend(r)
        elif isinstance(r, Exception):
            logger.warning("Yahoo RSS gather error: %s", r)
    return articles


# ---------------------------------------------------------------------------
# Source: Nasdaq Nordic (for Finnish/Nordic stocks)
# ---------------------------------------------------------------------------

async def fetch_nasdaq_nordic(isin: str, symbol: str | None = None) -> list[dict]:
    """Fetch company news from Nasdaq Nordic for a given ISIN."""
    url = "https://api.news.eu.nasdaq.com/news/query.action"
    params = {
        "type": "releasedetail",
        "displayLanguage": "en",
        "company": isin,
        "limit": 20,
    }

    articles: list[dict] = []
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        # Nasdaq Nordic API response structure varies — handle both shapes
        items_raw = data.get("results", data.get("news", {}).get("item", []))
        if isinstance(items_raw, dict):
            items_raw = items_raw.get("item", [])
        if not isinstance(items_raw, list):
            items_raw = []

        for item in items_raw:
            if not isinstance(item, dict):
                continue
            title = (item.get("headline") or item.get("title") or "")[:500]
            link = item.get("newsId") or item.get("link") or ""
            # Build URL if only id
            if link and not link.startswith("http"):
                link = f"https://www.nasdaqomxnordic.com/news/companynews/{link}"
            published_str = item.get("published") or item.get("releaseTime") or ""
            published = _parse_iso(published_str)
            articles.append({
                "symbol": symbol,
                "title": title,
                "summary": (item.get("preamble") or item.get("description") or "")[:2000] or None,
                "url": link,
                "source": "Nasdaq Nordic",
                "published_at": published,
            })
    except Exception:
        logger.exception("Nasdaq Nordic fetch failed for ISIN %s", isin)

    return articles


async def fetch_nasdaq_nordic_all(symbols: list[str]) -> list[dict]:
    """Fetch Nasdaq Nordic news for all Finnish/Nordic stocks concurrently."""
    tasks = []
    for sym in symbols:
        isin = symbol_metadata.isin(sym)
        if isin:
            tasks.append(fetch_nasdaq_nordic(isin, symbol=sym))
    if not tasks:
        return []
    results = await asyncio.gather(*tasks, return_exceptions=True)
    articles: list[dict] = []
    for r in results:
        if isinstance(r, list):
            articles.extend(r)
        elif isinstance(r, Exception):
            logger.warning("Nasdaq Nordic gather error: %s", r)
    return articles


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

async def poll_all_news(db: AsyncSession, symbols: list[str] | None = None) -> int:
    """Poll all news sources and store new articles. Returns count of new articles."""
    if symbols is None:
        result = await db.execute(select(Holding.symbol).distinct())
        symbols = list(result.scalars().all())
        if not symbols:
            symbols = symbol_metadata.all_symbols()
    else:
        symbols = list(symbols)

    logger.info("Polling news for %d symbols: %s", len(symbols), symbols)

    newsapi_key = settings.NEWS_API_KEY
    finnhub_key = settings.FINNHUB_API_KEY

    # Fetch from all sources in parallel
    results = await asyncio.gather(
        fetch_newsapi(symbols, newsapi_key),
        fetch_finnhub_all(symbols, finnhub_key),
        fetch_yahoo_all(symbols),
        fetch_nasdaq_nordic_all(symbols),
        return_exceptions=True,
    )

    all_articles: list[dict] = []
    source_names = ["NewsAPI", "Finnhub", "Yahoo RSS", "Nasdaq Nordic"]
    for i, r in enumerate(results):
        if isinstance(r, list):
            logger.info("  %s returned %d articles", source_names[i], len(r))
            all_articles.extend(r)
        elif isinstance(r, Exception):
            logger.warning("  %s failed: %s", source_names[i], r)

    # Deduplicate by URL
    seen_urls: set[str] = set()
    unique_articles: list[dict] = []
    for art in all_articles:
        url = art.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique_articles.append(art)

    logger.info("Total unique articles: %d", len(unique_articles))

    # Filter out articles already in DB
    existing_urls_result = await db.execute(
        select(NewsArticle.url).where(
            NewsArticle.url.in_([a["url"] for a in unique_articles if a.get("url")])
        )
    )
    existing_urls: set[str] = set(existing_urls_result.scalars().all())

    new_count = 0
    for art in unique_articles:
        url = art.get("url", "")
        if not url or url in existing_urls:
            continue

        sentiment = simple_sentiment(art.get("title", ""), art.get("summary"))
        published = art.get("published_at") or datetime.now(timezone.utc)
        # Convert to naive UTC (PostgreSQL timestamp without timezone)
        if isinstance(published, datetime) and published.tzinfo is not None:
            published = published.astimezone(timezone.utc).replace(tzinfo=None)

        article = NewsArticle(
            id=uuid.uuid4(),
            symbol=art.get("symbol"),
            title=art.get("title", "Untitled"),
            summary=art.get("summary"),
            url=url,
            source=art.get("source", "Unknown"),
            published_at=published,
            sentiment_score=Decimal(str(sentiment)),
        )
        db.add(article)
        new_count += 1

    await db.flush()
    logger.info("Stored %d new articles", new_count)
    return new_count


# ---------------------------------------------------------------------------
# Earnings calendar
# ---------------------------------------------------------------------------

async def get_upcoming_earnings(db: AsyncSession) -> list[dict]:
    """Get upcoming earnings dates for portfolio companies."""
    return await fetch_earnings_calendar(settings.FINNHUB_API_KEY)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_utc(dt: datetime) -> datetime:
    """Ensure a datetime is timezone-aware (assume UTC if naive)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _parse_iso(dt_str: str | None) -> datetime:
    """Parse an ISO-8601 datetime string, falling back to now(UTC)."""
    if not dt_str:
        return datetime.now(timezone.utc)
    try:
        # Handle 'Z' suffix
        dt_str = dt_str.replace("Z", "+00:00")
        return _ensure_utc(datetime.fromisoformat(dt_str))
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)


def _parse_rss_date(dt_str: str) -> datetime:
    """Parse RFC-822 / RSS date format, e.g. 'Mon, 21 Apr 2025 14:30:00 +0000'."""
    if not dt_str:
        return datetime.now(timezone.utc)
    # Common RSS date formats
    for fmt in (
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",
    ):
        try:
            return _ensure_utc(datetime.strptime(dt_str.strip(), fmt))
        except ValueError:
            continue
    return datetime.now(timezone.utc)
