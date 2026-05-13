"""Per-symbol metadata: data-source mappings, news keywords, sector info.

Previously hardcoded in service modules. Moved to the database so the public
source tree does not reveal which specific tickers a user holds and so that
operators can adjust symbol mappings without redeploying.
"""

from typing import Optional

from sqlalchemy import JSON, Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SymbolMetadata(Base):
    __tablename__ = "symbol_metadata"

    # Local symbol used inside the app (e.g. "AAPL", "MSFT", "GOOG").
    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)

    # Provider-specific symbol mappings.
    yahoo_symbol: Mapped[Optional[str]] = mapped_column(String(30), default=None)
    finnhub_symbol: Mapped[Optional[str]] = mapped_column(String(30), default=None)

    # Display / metadata.
    company_name: Mapped[Optional[str]] = mapped_column(String(255), default=None)
    isin: Mapped[Optional[str]] = mapped_column(String(12), default=None)
    sector: Mapped[Optional[str]] = mapped_column(String(100), default=None)
    industry: Mapped[Optional[str]] = mapped_column(String(255), default=None)
    country: Mapped[Optional[str]] = mapped_column(String(100), default=None)

    # News matching: list of lowercase keywords to look for in article text
    # beyond the company name itself. Stored as a JSON array.
    news_keywords: Mapped[Optional[list[str]]] = mapped_column(JSON, default=None)

    # Source-availability flags.
    has_finnhub_news: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    has_yahoo_news: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    # Symbol classification.
    is_crypto: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Skip in portfolio aggregations like sector breakdowns (e.g., index ETFs, crypto).
    skip_in_aggregations: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
