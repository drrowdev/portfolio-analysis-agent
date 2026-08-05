from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class AccountSummary(BaseModel):
    account_id: str
    account_name: str
    broker: str
    total_value_eur: Decimal
    total_cost_eur: Decimal
    unrealized_pnl_eur: Decimal
    unrealized_pnl_pct: Optional[Decimal]


class AllocationEntry(BaseModel):
    symbol: str
    instrument_name: str
    weight_pct: Decimal
    value_eur: Decimal


class PortfolioSummary(BaseModel):
    total_value_eur: Decimal
    total_cost_eur: Decimal
    total_unrealized_pnl_eur: Decimal
    total_unrealized_pnl_pct: Optional[Decimal]
    daily_pnl_eur: Optional[Decimal] = None
    daily_pnl_pct: Optional[Decimal] = None
    cash_available: Decimal = Decimal("0")
    accounts: list[AccountSummary]
    top_holdings: list[AllocationEntry]
    currency: str = "EUR"


class PerformanceDataPoint(BaseModel):
    date: date
    portfolio_return_pct: float
    sp500_return_pct: float
    portfolio_value_eur: float


class PerformanceResponse(BaseModel):
    period: str
    start_date: date
    benchmark_name: str = "S&P 500 Total Return"
    benchmark_ticker: str = "^SP500TR"
    currency: str = "EUR"
    methodology: str = (
        "Time-weighted market return of recorded invested holdings in EUR, using "
        "raw closes for market-value weights and adjusted-close relatives for total "
        "returns. Position changes are neutralized at the daily close; cash, fees, "
        "and taxes are excluded."
    )
    warnings: list[str] = Field(default_factory=list)
    data: list[PerformanceDataPoint]
