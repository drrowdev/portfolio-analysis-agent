"""Portfolio aggregation and P/L calculations."""

import asyncio
import hashlib
import json
import logging
import re
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pandas as pd
import yfinance as yf
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.account import Account
from app.models.holding import Holding
from app.models.transaction import Transaction
from app.schemas.portfolio import (
    AccountSummary,
    AllocationEntry,
    PerformanceDataPoint,
    PerformanceResponse,
    PortfolioSummary,
)
from app.services.market_data import _yf_symbol as _yf_symbol_lookup

logger = logging.getLogger(__name__)

BENCHMARK_NAME = "S&P 500 Total Return"
BENCHMARK_TICKER = "^SP500TR"
PERFORMANCE_CURRENCY = "EUR"
PERFORMANCE_METHODOLOGY = (
    "Time-weighted market return of recorded invested holdings in EUR, using "
    "raw closes for market-value weights and adjusted-close relatives for total "
    "returns. Position changes are neutralized at the daily close; cash, fees, "
    "and taxes are excluded."
)
_PRICE_LOOKBACK_DAYS = 14
_MAX_DATA_STALENESS_DAYS = 7
_POSITION_EPSILON = 1e-8
_RECONCILIATION_TOLERANCE = _POSITION_EPSILON
_PERFORMANCE_CACHE_PREFIX = "performance-v5-"
_ISO_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")
_SPLIT_ADJUSTMENT_NOTE_MARKERS = ("RAHASTOANTI",)

# In-memory cache: key -> (timestamp, source fingerprint, data)
_performance_cache: dict[str, tuple[float, str, PerformanceResponse]] = {}
_CACHE_TTL = 2 * 60 * 60  # 2 hours


async def compute_portfolio_summary(db: AsyncSession) -> PortfolioSummary:
    """Aggregate holdings across all accounts into a portfolio summary."""
    # Load all accounts with their holdings
    stmt = select(Account).options(selectinload(Account.holdings))
    result = await db.execute(stmt)
    accounts = list(result.scalars().all())

    # Fetch cash available from user settings
    from app.models.user_settings import UserSetting
    cash_result = await db.execute(
        select(UserSetting).where(UserSetting.key == "cash_available")
    )
    cash_setting = cash_result.scalar_one_or_none()
    cash_available = Decimal(cash_setting.value) if cash_setting else Decimal("0")

    total_value = Decimal("0")
    total_cost = Decimal("0")
    daily_pnl = Decimal("0")
    account_summaries: list[AccountSummary] = []
    all_holdings: list[dict] = []

    for account in accounts:
        acct_value = Decimal("0")
        acct_cost = Decimal("0")

        for holding in account.holdings:
            # All holding values (*_eur fields) are already in EUR
            cost_eur = holding.total_cost_eur or Decimal("0")
            value_eur = holding.current_value_eur or cost_eur

            acct_cost += cost_eur
            acct_value += value_eur

            # Calculate today's change for this holding
            if holding.price_change_pct is not None and value_eur > 0:
                # value_eur = qty * current_price; yesterday's value = value_eur / (1 + change%)
                change_factor = holding.price_change_pct / Decimal("100")
                daily_change = value_eur - (value_eur / (1 + change_factor))
                daily_pnl += daily_change

            all_holdings.append({
                "symbol": holding.symbol,
                "instrument_name": holding.instrument_name,
                "value_eur": value_eur,
                "cost_eur": cost_eur,
            })

        acct_pnl = acct_value - acct_cost
        acct_pnl_pct = (
            (acct_pnl / acct_cost * 100) if acct_cost else None
        )

        account_summaries.append(
            AccountSummary(
                account_id=str(account.id),
                account_name=account.name,
                broker=account.broker,
                total_value_eur=acct_value.quantize(Decimal("0.01")),
                total_cost_eur=acct_cost.quantize(Decimal("0.01")),
                unrealized_pnl_eur=acct_pnl.quantize(Decimal("0.01")),
                unrealized_pnl_pct=(
                    acct_pnl_pct.quantize(Decimal("0.01")) if acct_pnl_pct else None
                ),
            )
        )

        total_value += acct_value
        total_cost += acct_cost

    # Add cash to total value (cash is not a cost/investment, so only add to value)
    total_value_with_cash = total_value + cash_available

    total_pnl = total_value - total_cost
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost else None

    # Build allocation entries sorted by value — weights based on total including cash
    top_holdings: list[AllocationEntry] = []
    for h in sorted(all_holdings, key=lambda x: x["value_eur"], reverse=True):
        weight = (h["value_eur"] / total_value_with_cash * 100) if total_value_with_cash else Decimal("0")
        top_holdings.append(
            AllocationEntry(
                symbol=h["symbol"],
                instrument_name=h["instrument_name"],
                weight_pct=weight.quantize(Decimal("0.01")),
                value_eur=h["value_eur"].quantize(Decimal("0.01")),
            )
        )

    # Compute daily P&L percentage relative to yesterday's portfolio value
    yesterday_value = total_value - daily_pnl
    daily_pnl_pct = (daily_pnl / yesterday_value * 100) if yesterday_value else None

    return PortfolioSummary(
        total_value_eur=total_value_with_cash.quantize(Decimal("0.01")),
        total_cost_eur=total_cost.quantize(Decimal("0.01")),
        total_unrealized_pnl_eur=total_pnl.quantize(Decimal("0.01")),
        total_unrealized_pnl_pct=(
            total_pnl_pct.quantize(Decimal("0.01")) if total_pnl_pct else None
        ),
        daily_pnl_eur=daily_pnl.quantize(Decimal("0.01")),
        daily_pnl_pct=(
            daily_pnl_pct.quantize(Decimal("0.01")) if daily_pnl_pct else None
        ),
        cash_available=cash_available.quantize(Decimal("0.01")),
        accounts=account_summaries,
        top_holdings=top_holdings,
    )


# ---------------------------------------------------------------------------
# Performance comparison: portfolio vs S&P 500
# ---------------------------------------------------------------------------

PERIOD_MAP = {
    "1m": 30,
    "3m": 90,
    "6m": 180,
    "1y": 365,
}

_POSITION_INCREASE_TYPES = {"buy", "espp_purchase", "deposit"}
_POSITION_DECREASE_TYPES = {"sell", "espp_sale", "withdrawal"}


class PerformanceDataUnavailableError(RuntimeError):
    """Raised when required market or FX data cannot be valued reliably."""


def _resolve_period(period: str, earliest_tx_date: date) -> date:
    """Return the start date for the requested period."""
    today = date.today()
    period = period.lower()
    if period == "ytd":
        return date(today.year, 1, 1)
    if period == "all":
        return earliest_tx_date
    days = PERIOD_MAP.get(period, 365)
    return today - timedelta(days=days)


def _yf_symbol(symbol: str) -> str:
    return _yf_symbol_lookup(symbol)


def _statement_snapshot_date(notes: str) -> date | None:
    """Extract the source statement date from supported importer notes."""
    if not (
        notes.startswith("Imported from Nordnet lot export")
        or notes.startswith("Fidelity ")
    ):
        return None
    matches = _ISO_DATE_PATTERN.findall(notes)
    return date.fromisoformat(matches[-1]) if matches else None


def _performance_source_fingerprint(
    transactions: list[dict[str, Any]],
    holdings_info: list[dict[str, Any]],
) -> str:
    """Hash every source field that can change a cached performance result."""
    tx_rows = sorted(
        (
            str(t.get("account_id", "")),
            str(t["symbol"]),
            _yf_symbol(str(t["symbol"])),
            str(t["date"]),
            str(t["quantity"]),
            str(t["transaction_type"]),
            str(t["currency"]).upper(),
            str(t.get("total_eur", "")),
            str(t.get("notes", "")),
        )
        for t in transactions
    )
    holding_rows = sorted(
        (
            str(h.get("account_id", "")),
            str(h["symbol"]),
            str(h["currency"]).upper(),
            str(h.get("total_quantity", "")),
            str(h.get("snapshot_date", "")),
            _yf_symbol(str(h["symbol"])),
        )
        for h in holdings_info
    )
    payload = json.dumps(
        {
            "as_of_date": date.today().isoformat(),
            "transactions": tx_rows,
            "holdings": holding_rows,
        },
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _add_opening_balance_transactions(
    transactions: list[dict[str, Any]],
    holdings_info: list[dict[str, Any]],
) -> list[str]:
    """Reconcile split-adjusted transaction history to current holdings."""
    tx_qty_by_position: dict[tuple[str, str], float] = defaultdict(float)
    tx_deltas_by_position: dict[
        tuple[str, str], dict[date, float]
    ] = defaultdict(
        lambda: defaultdict(float)
    )
    tx_currency_by_position: dict[tuple[str, str], str] = {}
    earliest_tx_by_position: dict[tuple[str, str], date] = {}
    for transaction in transactions:
        if transaction["transaction_type"] in _POSITION_INCREASE_TYPES:
            direction = 1.0
        elif transaction["transaction_type"] in _POSITION_DECREASE_TYPES:
            direction = -1.0
        else:
            continue
        if transaction["date"] > date.today():
            raise PerformanceDataUnavailableError(
                f"{transaction['symbol']} has a future-dated position change."
            )

        symbol = transaction["symbol"]
        account_id = str(transaction.get("account_id", ""))
        position_key = (account_id, symbol)
        quantity = float(transaction["quantity"])
        currency = str(transaction["currency"]).upper()
        previous_currency = tx_currency_by_position.get(position_key)
        if previous_currency and previous_currency != currency:
            raise PerformanceDataUnavailableError(
                f"{symbol} has transactions in multiple currencies."
            )
        tx_currency_by_position[position_key] = currency
        delta = direction * quantity
        tx_qty_by_position[position_key] += delta
        tx_deltas_by_position[position_key][transaction["date"]] += delta
        earliest_tx_by_position[position_key] = min(
            earliest_tx_by_position.get(position_key, transaction["date"]),
            transaction["date"],
        )

    holding_qty_by_position: dict[tuple[str, str], float] = defaultdict(float)
    holding_currency_by_position: dict[tuple[str, str], str] = {}
    holding_snapshot_by_position: dict[tuple[str, str], date] = {}
    for holding in holdings_info:
        symbol = holding["symbol"]
        account_id = str(holding.get("account_id", ""))
        position_key = (account_id, symbol)
        currency = str(holding["currency"]).upper()
        previous_currency = holding_currency_by_position.get(position_key)
        if previous_currency and previous_currency != currency:
            raise PerformanceDataUnavailableError(
                f"{symbol} has holdings in multiple currencies."
            )
        transaction_currency = tx_currency_by_position.get(position_key)
        if transaction_currency and transaction_currency != currency:
            raise PerformanceDataUnavailableError(
                f"{symbol} transactions and holdings use different currencies."
            )
        holding_currency_by_position[position_key] = currency
        holding_qty_by_position[position_key] += float(
            holding.get("total_quantity", 0)
        )
        snapshot_date = holding.get("snapshot_date") or date.today()
        if isinstance(snapshot_date, datetime):
            snapshot_date = snapshot_date.date()
        if snapshot_date > date.today():
            raise PerformanceDataUnavailableError(
                f"{symbol} has a future-dated holding snapshot."
            )
        holding_snapshot_by_position[position_key] = max(
            holding_snapshot_by_position.get(position_key, snapshot_date),
            snapshot_date,
        )

    warnings: list[str] = []
    position_keys = set(tx_qty_by_position) | set(holding_qty_by_position)
    for position_key in position_keys:
        account_id, symbol = position_key
        holding_quantity = holding_qty_by_position.get(position_key, 0.0)
        snapshot_date = holding_snapshot_by_position.get(
            position_key,
            date.today(),
        )
        deltas = tx_deltas_by_position[position_key]
        post_snapshot_delta = sum(
            delta
            for transaction_date, delta in deltas.items()
            if transaction_date > snapshot_date
        )
        snapshot_quantity = holding_quantity - post_snapshot_delta
        if snapshot_quantity < -_RECONCILIATION_TOLERANCE:
            raise PerformanceDataUnavailableError(
                f"Recorded post-snapshot transactions for {symbol} cannot be "
                "reconciled to the current holding quantity."
            )

        recorded_through_snapshot = sum(
            delta
            for transaction_date, delta in deltas.items()
            if transaction_date <= snapshot_date
        )
        gap = snapshot_quantity - recorded_through_snapshot
        if gap < -_RECONCILIATION_TOLERANCE:
            raise PerformanceDataUnavailableError(
                f"Recorded transactions for {symbol} exceed the holding quantity "
                "at its snapshot."
            )

        running_quantity = 0.0
        minimum_quantity = 0.0
        for transaction_date in sorted(deltas):
            if transaction_date > snapshot_date:
                break
            running_quantity += deltas[transaction_date]
            minimum_quantity = min(minimum_quantity, running_quantity)

        required_pre_history = max(0.0, -minimum_quantity)
        if required_pre_history > gap + _RECONCILIATION_TOLERANCE:
            raise PerformanceDataUnavailableError(
                f"Recorded transaction history for {symbol} cannot be reconciled "
                "to the current holding quantity."
            )

        running_quantity = snapshot_quantity
        for transaction_date in sorted(deltas):
            if transaction_date <= snapshot_date:
                continue
            running_quantity += deltas[transaction_date]
            if running_quantity < -_RECONCILIATION_TOLERANCE:
                raise PerformanceDataUnavailableError(
                    f"Recorded post-snapshot transactions for {symbol} create "
                    "a negative position."
                )
        if gap <= _RECONCILIATION_TOLERANCE:
            continue

        currency = (
            holding_currency_by_position.get(position_key)
            or tx_currency_by_position[position_key]
        )
        if required_pre_history > _RECONCILIATION_TOLERANCE:
            earliest_date = earliest_tx_by_position[position_key]
            transactions.append(
                {
                    "account_id": account_id,
                    "symbol": symbol,
                    "date": earliest_date,
                    "quantity": required_pre_history,
                    "total_eur": 0.0,
                    "transaction_type": "buy",
                    "currency": currency,
                    "notes": "Opening balance: inferred pre-history",
                }
            )
            warnings.append(
                f"{symbol}: inferred the minimum opening balance needed to cover "
                "recorded sales; returns before the earliest recorded transaction "
                "cannot be verified."
            )

        snapshot_balance = max(0.0, gap - required_pre_history)
        if snapshot_balance > _RECONCILIATION_TOLERANCE:
            transactions.append(
                {
                    "account_id": account_id,
                    "symbol": symbol,
                    "date": snapshot_date,
                    "quantity": snapshot_balance,
                    "total_eur": 0.0,
                    "transaction_type": "buy",
                    "currency": currency,
                    "notes": "Opening balance: holding snapshot",
                }
            )
            warnings.append(
                f"{symbol}: inferred the remaining opening balance at the "
                f"{snapshot_date.isoformat()} holding snapshot; performance before "
                "that date excludes those shares."
            )

    return list(dict.fromkeys(warnings))


def _split_factor_after(
    yahoo_symbol: str,
    basis_date: date,
    split_events: pd.DataFrame,
) -> float:
    split_factor = 1.0
    if yahoo_symbol in split_events.columns:
        for timestamp, ratio in split_events[yahoo_symbol].dropna().items():
            ratio_value = float(ratio)
            if timestamp.date() > basis_date and ratio_value > 0:
                split_factor *= ratio_value
    return split_factor


def _is_provider_normalized_split_adjustment(
    transaction: dict[str, Any],
) -> bool:
    notes = str(transaction.get("notes", "")).upper()
    return notes.startswith("POSITION ADJUSTMENT:") and any(
        marker in notes
        for marker in _SPLIT_ADJUSTMENT_NOTE_MARKERS
    )


def _adjust_transactions_for_splits(
    transactions: list[dict[str, Any]],
    split_events: pd.DataFrame,
    symbol_to_yahoo: dict[str, str],
) -> list[dict[str, Any]]:
    """Convert transaction quantities to the current split-adjusted share basis."""
    adjusted: list[dict[str, Any]] = []
    for transaction in transactions:
        if _is_provider_normalized_split_adjustment(transaction):
            continue
        yahoo_symbol = symbol_to_yahoo.get(transaction["symbol"])
        notes = str(transaction.get("notes", ""))
        basis_date = (
            _statement_snapshot_date(notes)
            if notes.startswith("Imported from Nordnet lot export")
            else None
        ) or transaction["date"]
        split_factor = (
            _split_factor_after(yahoo_symbol, basis_date, split_events)
            if yahoo_symbol
            else 1.0
        )
        adjusted.append(
            {
                **transaction,
                "quantity": float(transaction["quantity"]) * split_factor,
            }
        )
    return adjusted


def _deduplicate_split_events(split_events: pd.DataFrame) -> pd.DataFrame:
    """Collapse a total split ratio plus its nearby bonus-share ratio."""
    deduplicated = split_events.copy()
    for ticker in deduplicated.columns:
        events = [
            (timestamp, float(ratio))
            for timestamp, ratio in deduplicated[ticker].dropna().items()
            if float(ratio) > 1
        ]
        for index, (timestamp, ratio) in enumerate(events):
            for other_timestamp, other_ratio in events[index + 1:]:
                if (other_timestamp.date() - timestamp.date()).days > 7:
                    break
                larger = max(ratio, other_ratio)
                smaller = min(ratio, other_ratio)
                if abs(larger - (smaller + 1)) <= _POSITION_EPSILON:
                    duplicate_timestamp = (
                        timestamp if ratio == smaller else other_timestamp
                    )
                    deduplicated.at[duplicate_timestamp, ticker] = 0.0
    return deduplicated


def _adjust_holdings_for_splits(
    holdings_info: list[dict[str, Any]],
    transactions: list[dict[str, Any]],
    split_events: pd.DataFrame,
    symbol_to_yahoo: dict[str, str],
) -> list[dict[str, Any]]:
    """Convert holding snapshots to the current split-adjusted share basis."""
    holdings_by_position: dict[
        tuple[str, str],
        list[dict[str, Any]],
    ] = defaultdict(list)
    for holding in holdings_info:
        position_key = (
            str(holding.get("account_id", "")),
            holding["symbol"],
        )
        holdings_by_position[position_key].append(holding)

    adjusted: list[dict[str, Any]] = []
    for position_key, position_holdings in holdings_by_position.items():
        account_id, symbol = position_key
        snapshot_dates = {
            (
                holding["snapshot_date"].date()
                if isinstance(holding.get("snapshot_date"), datetime)
                else holding.get("snapshot_date") or date.today()
            )
            for holding in position_holdings
        }
        if len(snapshot_dates) != 1:
            raise PerformanceDataUnavailableError(
                f"{symbol} has holdings from multiple snapshot dates."
            )
        snapshot_date = snapshot_dates.pop()
        yahoo_symbol = symbol_to_yahoo[symbol]
        snapshot_split_factor = _split_factor_after(
            yahoo_symbol,
            snapshot_date,
            split_events,
        )
        raw_post_snapshot_delta = 0.0
        adjusted_post_snapshot_delta = 0.0
        for transaction in transactions:
            if (
                str(transaction.get("account_id", "")) != account_id
                or transaction["symbol"] != symbol
                or transaction["date"] <= snapshot_date
            ):
                continue
            if transaction["transaction_type"] in _POSITION_INCREASE_TYPES:
                direction = 1.0
            elif transaction["transaction_type"] in _POSITION_DECREASE_TYPES:
                direction = -1.0
            else:
                continue
            quantity = float(transaction["quantity"])
            notes = str(transaction.get("notes", ""))
            basis_date = (
                _statement_snapshot_date(notes)
                if notes.startswith("Imported from Nordnet lot export")
                else None
            ) or transaction["date"]
            transaction_split_factor = _split_factor_after(
                yahoo_symbol,
                basis_date,
                split_events,
            )
            raw_post_snapshot_delta += direction * quantity
            if not _is_provider_normalized_split_adjustment(transaction):
                adjusted_post_snapshot_delta += (
                    direction * quantity * transaction_split_factor
                )

        raw_holding_quantity = sum(
            float(holding.get("total_quantity", 0))
            for holding in position_holdings
        )
        raw_snapshot_quantity = (
            raw_holding_quantity - raw_post_snapshot_delta
        )
        first_holding = position_holdings[0]
        adjusted.append(
            {
                **first_holding,
                "snapshot_date": snapshot_date,
                "total_quantity": (
                    raw_snapshot_quantity * snapshot_split_factor
                    + adjusted_post_snapshot_delta
                ),
                "total_cost_eur": sum(
                    float(holding.get("total_cost_eur", 0))
                    for holding in position_holdings
                ),
            }
        )
    return adjusted


def _compute_performance_sync(
    transactions: list[dict[str, Any]],
    holdings_info: list[dict[str, Any]],
    period: str,
    warnings: list[str] | None = None,
) -> PerformanceResponse:
    """Fetch market data and compute an EUR-denominated time-weighted return.

    ``transactions`` – list of dicts with keys: symbol, date, quantity, transaction_type, currency
    ``holdings_info`` – list of dicts with keys: symbol, currency, total_quantity, snapshot_date
    """
    warnings = list(warnings or [])
    today = date.today()

    def _position_key(row: dict[str, Any]) -> tuple[str, str]:
        return str(row.get("account_id", "")), str(row["symbol"])

    for transaction in transactions:
        is_position_change = (
            transaction["transaction_type"] in _POSITION_INCREASE_TYPES
            or transaction["transaction_type"] in _POSITION_DECREASE_TYPES
        ) and abs(float(transaction["quantity"])) > _POSITION_EPSILON
        if is_position_change and transaction["date"] > today:
            raise PerformanceDataUnavailableError(
                f"{transaction['symbol']} has a future-dated position change."
            )
    position_transactions = [
        transaction
        for transaction in transactions
        if (
            transaction["transaction_type"] in _POSITION_INCREASE_TYPES
            or transaction["transaction_type"] in _POSITION_DECREASE_TYPES
        )
        and abs(float(transaction["quantity"])) > _POSITION_EPSILON
        and not _is_provider_normalized_split_adjustment(transaction)
    ]
    transaction_position_keys = {
        _position_key(transaction)
        for transaction in position_transactions
    }
    holding_snapshot_dates: list[date] = []
    for holding in holdings_info:
        snapshot_date = (
            holding["snapshot_date"].date()
            if isinstance(holding.get("snapshot_date"), datetime)
            else holding.get("snapshot_date") or today
        )
        if snapshot_date > today:
            raise PerformanceDataUnavailableError(
                f"{holding['symbol']} has a future-dated holding snapshot."
            )
        if (
            float(holding.get("total_quantity", 0)) > _POSITION_EPSILON
            or _position_key(holding) in transaction_position_keys
        ):
            holding_snapshot_dates.append(snapshot_date)
    source_dates = [
        transaction["date"]
        for transaction in position_transactions
    ] + holding_snapshot_dates
    if not source_dates:
        return PerformanceResponse(
            period=period,
            start_date=date.today(),
            data=[],
            warnings=warnings,
        )

    transactions = sorted(transactions, key=lambda t: t["date"])
    earliest_source_date = min(source_dates)
    start = _resolve_period(period, earliest_source_date)
    end = today + timedelta(days=1)  # yfinance end is exclusive

    if start < earliest_source_date:
        start = earliest_source_date

    base_relevant_positions: set[tuple[str, str]] | None = None
    if period.lower() != "all":
        base_relevant_positions = {
            _position_key(holding)
            for holding in holdings_info
            if (
                float(holding.get("total_quantity", 0)) > _POSITION_EPSILON
                or _position_key(holding) in transaction_position_keys
            )
        }
        base_relevant_positions.update(
            _position_key(transaction)
            for transaction in position_transactions
            if transaction["date"] >= start
        )
        position_transactions = [
            transaction
            for transaction in position_transactions
            if _position_key(transaction) in base_relevant_positions
        ]
        transactions = [
            transaction
            for transaction in transactions
            if (
                transaction["transaction_type"] not in _POSITION_INCREASE_TYPES
                and transaction["transaction_type"] not in _POSITION_DECREASE_TYPES
            )
            or _position_key(transaction) in base_relevant_positions
        ]
        holdings_info = [
            holding
            for holding in holdings_info
            if _position_key(holding) in base_relevant_positions
        ]

    holding_position_keys = {
        _position_key(holding)
        for holding in holdings_info
    }

    def _unreconciled_orphan_positions(
        rows: list[dict[str, Any]],
    ) -> set[tuple[str, str]]:
        deltas: dict[
            tuple[str, str],
            dict[date, float],
        ] = defaultdict(lambda: defaultdict(float))
        for transaction in rows:
            if transaction["transaction_type"] in _POSITION_INCREASE_TYPES:
                direction = 1.0
            elif transaction["transaction_type"] in _POSITION_DECREASE_TYPES:
                direction = -1.0
            else:
                continue
            deltas[_position_key(transaction)][transaction["date"]] += (
                direction * float(transaction["quantity"])
            )

        unreconciled: set[tuple[str, str]] = set()
        for position_key, daily_deltas in deltas.items():
            if position_key in holding_position_keys:
                continue
            running_quantity = 0.0
            for transaction_date in sorted(daily_deltas):
                running_quantity += daily_deltas[transaction_date]
                if running_quantity < -_RECONCILIATION_TOLERANCE:
                    unreconciled.add(position_key)
                    break
            if abs(running_quantity) > _RECONCILIATION_TOLERANCE:
                unreconciled.add(position_key)
        return unreconciled

    omitted_unreconciled_positions: set[tuple[str, str]] = set()

    def _append_omitted_history_warning() -> None:
        if not omitted_unreconciled_positions:
            return
        omitted_symbols = ", ".join(
            sorted({
                symbol
                for _, symbol in omitted_unreconciled_positions
            })
        )
        warnings.append(
            "Omitted incomplete transaction histories for "
            f"{omitted_symbols} because they do not reconcile to the current "
            "holdings snapshot."
        )

    if base_relevant_positions is not None:
        directions_by_position: dict[
            tuple[str, str],
            set[int],
        ] = defaultdict(set)
        for transaction in position_transactions:
            if transaction["transaction_type"] in _POSITION_INCREASE_TYPES:
                direction = 1
            elif transaction["transaction_type"] in _POSITION_DECREASE_TYPES:
                direction = -1
            else:
                continue
            directions_by_position[_position_key(transaction)].add(direction)
        omitted_unreconciled_positions.update(
            position_key
            for position_key, directions in directions_by_position.items()
            if position_key not in holding_position_keys and len(directions) == 1
        )
        position_transactions = [
            transaction
            for transaction in position_transactions
            if _position_key(transaction) not in omitted_unreconciled_positions
        ]
        transactions = [
            transaction
            for transaction in transactions
            if (
                transaction["transaction_type"] not in _POSITION_INCREASE_TYPES
                and transaction["transaction_type"] not in _POSITION_DECREASE_TYPES
            )
            or _position_key(transaction)
            not in omitted_unreconciled_positions
        ]

    # Collect unique position symbols and reject ambiguous currency metadata.
    symbol_currencies: dict[str, str] = {}

    def _register_currency(symbol: str, currency: str) -> None:
        normalized = currency.upper()
        existing = symbol_currencies.get(symbol)
        if existing and existing != normalized:
            raise PerformanceDataUnavailableError(
                f"{symbol} has transactions or holdings in multiple currencies."
            )
        symbol_currencies[symbol] = normalized

    for h in holdings_info:
        _register_currency(h["symbol"], h["currency"])
    for t in transactions:
        if (
            t["transaction_type"] in _POSITION_INCREASE_TYPES
            or t["transaction_type"] in _POSITION_DECREASE_TYPES
        ) and float(t["quantity"]) != 0:
            _register_currency(t["symbol"], t["currency"])

    symbols = list(symbol_currencies.keys())
    if not symbols:
        _append_omitted_history_warning()
        return PerformanceResponse(
            period=period,
            start_date=start,
            data=[],
            warnings=warnings,
        )

    # Fetch a lookback buffer so forward-fill has a prior close when the
    # requested period begins on a holiday in one of the represented markets.
    sym_to_yf = {symbol: _yf_symbol(symbol) for symbol in symbols}
    fx_tickers = {
        currency: f"EUR{currency}=X"
        for currency in set(symbol_currencies.values()) | {"USD"}
        if currency != PERFORMANCE_CURRENCY
    }
    all_tickers = list(
        dict.fromkeys(
            [*sym_to_yf.values(), BENCHMARK_TICKER, *fx_tickers.values()]
        )
    )
    download_start = start - timedelta(days=_PRICE_LOOKBACK_DAYS)

    try:
        raw = yf.download(
            all_tickers,
            start=str(download_start),
            end=str(end),
            auto_adjust=False,
            actions=True,
            progress=False,
        )
    except Exception as e:
        logger.error("yfinance download failed: %s", e)
        raise PerformanceDataUnavailableError(
            "Historical market data is temporarily unavailable."
        ) from e

    if raw.empty:
        raise PerformanceDataUnavailableError(
            "Historical market data returned no prices."
        )

    def _extract_field(
        frame: pd.DataFrame,
        field: str,
        fallback_ticker: str,
    ) -> pd.DataFrame:
        if isinstance(frame.columns, pd.MultiIndex):
            if field in frame.columns.get_level_values(0):
                extracted = frame[field]
            elif field in frame.columns.get_level_values(-1):
                extracted = frame.xs(field, axis=1, level=-1)
            else:
                return pd.DataFrame(index=frame.index)
        elif field in frame.columns:
            extracted = frame[[field]].rename(columns={field: fallback_ticker})
        else:
            return pd.DataFrame(index=frame.index)

        if isinstance(extracted, pd.Series):
            extracted = extracted.to_frame(name=fallback_ticker)
        if isinstance(extracted.columns, pd.MultiIndex):
            extracted.columns = extracted.columns.get_level_values(-1)
        extracted.columns = [str(column) for column in extracted.columns]
        return extracted

    close = _extract_field(raw, "Close", all_tickers[0])
    if close.empty:
        raise PerformanceDataUnavailableError(
            "Historical market data did not contain closing prices."
        )
    close = close.sort_index()
    adjusted_close = _extract_field(
        raw,
        "Adj Close",
        all_tickers[0],
    ).sort_index()
    if adjusted_close.empty:
        raise PerformanceDataUnavailableError(
            "Historical market data did not contain adjusted closing prices."
        )
    split_events = _extract_field(
        raw,
        "Stock Splits",
        all_tickers[0],
    ).sort_index()

    if base_relevant_positions is not None:
        priced_symbols = {
            symbol
            for symbol, yahoo_symbol in sym_to_yf.items()
            if (
                yahoo_symbol in close.columns
                and not close[yahoo_symbol].dropna().empty
                and yahoo_symbol in adjusted_close.columns
                and not adjusted_close[yahoo_symbol].dropna().empty
            )
        }
        unpriced_symbols = {
            row["symbol"]
            for row in [*position_transactions, *holdings_info]
            if row["symbol"] not in priced_symbols
        }
        if unpriced_symbols:
            missing = ", ".join(sorted(unpriced_symbols))
            raise PerformanceDataUnavailableError(
                f"Historical prices are unavailable for {missing}."
            )

    split_basis_dates: dict[str, date] = {}
    for transaction in position_transactions:
        yahoo_symbol = sym_to_yf[transaction["symbol"]]
        notes = str(transaction.get("notes", ""))
        basis_date = (
            _statement_snapshot_date(notes)
            if notes.startswith("Imported from Nordnet lot export")
            else None
        ) or transaction["date"]
        split_basis_dates[yahoo_symbol] = min(
            split_basis_dates.get(yahoo_symbol, basis_date),
            basis_date,
        )
    for holding in holdings_info:
        yahoo_symbol = sym_to_yf[holding["symbol"]]
        snapshot_date = holding.get("snapshot_date") or date.today()
        if isinstance(snapshot_date, datetime):
            snapshot_date = snapshot_date.date()
        split_basis_dates[yahoo_symbol] = min(
            split_basis_dates.get(yahoo_symbol, snapshot_date),
            snapshot_date,
        )

    required_split_tickers = set(split_basis_dates)
    missing_split_tickers = required_split_tickers - set(split_events.columns)
    missing_split_tickers.update(
        ticker
        for ticker in required_split_tickers & set(split_events.columns)
        if split_events[ticker].notna().sum() == 0
    )
    if missing_split_tickers:
        missing = ", ".join(sorted(missing_split_tickers))
        raise PerformanceDataUnavailableError(
            f"Stock-split data is unavailable for {missing}."
        )

    old_split_tickers = [
        ticker
        for ticker, basis_date in split_basis_dates.items()
        if basis_date < download_start
    ]
    earliest_split_basis = min(
        (split_basis_dates[ticker] for ticker in old_split_tickers),
        default=download_start,
    )
    if old_split_tickers and earliest_split_basis < download_start:
        try:
            old_actions = yf.download(
                old_split_tickers,
                start=str(earliest_split_basis),
                end=str(download_start),
                auto_adjust=False,
                actions=True,
                progress=False,
            )
        except Exception as exc:
            logger.error("Historical split download failed: %s", exc)
            raise PerformanceDataUnavailableError(
                "Historical stock-split data is temporarily unavailable."
            ) from exc
        if old_actions.empty:
            raise PerformanceDataUnavailableError(
                "Historical stock-split data returned no observations."
            )
        old_split_events = _extract_field(
            old_actions,
            "Stock Splits",
            old_split_tickers[0],
        )
        old_close = _extract_field(
            old_actions,
            "Close",
            old_split_tickers[0],
        )
        missing_split_tickers = set(old_split_tickers) - set(
            old_split_events.columns
        )
        missing_split_tickers.update(
            ticker
            for ticker in set(old_split_tickers) & set(old_split_events.columns)
            if old_split_events[ticker].notna().sum() == 0
        )
        for ticker in old_split_tickers:
            if ticker not in old_close.columns:
                missing_split_tickers.add(ticker)
                continue
            observations = old_close[ticker].dropna()
            if observations.empty:
                missing_split_tickers.add(ticker)
                continue
            first_observation = observations.index[0].date()
            last_observation = observations.index[-1].date()
            if (
                (first_observation - split_basis_dates[ticker]).days
                > _MAX_DATA_STALENESS_DAYS
                or (download_start - last_observation).days
                > _MAX_DATA_STALENESS_DAYS
            ):
                missing_split_tickers.add(ticker)
        if missing_split_tickers:
            missing = ", ".join(sorted(missing_split_tickers))
            raise PerformanceDataUnavailableError(
                f"Historical stock-split data is unavailable for {missing}."
            )
        split_events = pd.concat(
            [old_split_events, split_events]
        ).sort_index()
        split_events = split_events[
            ~split_events.index.duplicated(keep="last")
        ]
    split_events = _deduplicate_split_events(split_events)

    holdings_info = _adjust_holdings_for_splits(
        holdings_info,
        transactions,
        split_events,
        sym_to_yf,
    )
    transactions = _adjust_transactions_for_splits(
        transactions,
        split_events,
        sym_to_yf,
    )
    if base_relevant_positions is not None:
        adjusted_position_transactions = [
            transaction
            for transaction in transactions
            if (
                transaction["transaction_type"] in _POSITION_INCREASE_TYPES
                or transaction["transaction_type"] in _POSITION_DECREASE_TYPES
            )
            and abs(float(transaction["quantity"])) > _POSITION_EPSILON
        ]
        omitted_unreconciled_positions.update(
            _unreconciled_orphan_positions(adjusted_position_transactions)
        )
        if omitted_unreconciled_positions:
            transactions = [
                transaction
                for transaction in transactions
                if (
                    transaction["transaction_type"]
                    not in _POSITION_INCREASE_TYPES
                    and transaction["transaction_type"]
                    not in _POSITION_DECREASE_TYPES
                )
                or _position_key(transaction)
                not in omitted_unreconciled_positions
            ]
            _append_omitted_history_warning()
    warnings.extend(
        _add_opening_balance_transactions(transactions, holdings_info)
    )
    transactions.sort(key=lambda transaction: transaction["date"])

    retained_symbols = {
        transaction["symbol"]
        for transaction in transactions
        if (
            transaction["transaction_type"] in _POSITION_INCREASE_TYPES
            or transaction["transaction_type"] in _POSITION_DECREASE_TYPES
        )
        and abs(float(transaction["quantity"])) > _POSITION_EPSILON
    } | {
        holding["symbol"]
        for holding in holdings_info
    }

    if BENCHMARK_TICKER not in close.columns:
        raise PerformanceDataUnavailableError(
            f"{BENCHMARK_NAME} data is temporarily unavailable."
        )

    # Chart the requested baseline plus actual S&P 500 trading sessions. Other
    # markets and FX series are forward-filled onto those dates.
    analysis_index = close.index.union(
        pd.DatetimeIndex([pd.Timestamp(start)])
    ).sort_values()
    observed_close = close.reindex(analysis_index)
    observed_adjusted_close = adjusted_close.reindex(analysis_index)
    for symbol in retained_symbols:
        yahoo_symbol = sym_to_yf[symbol]
        if (
            yahoo_symbol not in observed_close.columns
            or yahoo_symbol not in observed_adjusted_close.columns
        ):
            continue
        raw_available = observed_close[yahoo_symbol].notna()
        adjusted_available = observed_adjusted_close[yahoo_symbol].notna()
        if not raw_available.equals(adjusted_available):
            raise PerformanceDataUnavailableError(
                f"Raw and adjusted historical prices for {symbol} are inconsistent."
            )
    for holding in holdings_info:
        if float(holding.get("total_quantity", 0)) <= _POSITION_EPSILON:
            continue
        yahoo_symbol = sym_to_yf[holding["symbol"]]
        if (
            yahoo_symbol not in observed_close.columns
            or observed_close[yahoo_symbol].dropna().empty
            or yahoo_symbol not in observed_adjusted_close.columns
            or observed_adjusted_close[yahoo_symbol].dropna().empty
        ):
            raise PerformanceDataUnavailableError(
                f"Historical prices for {holding['symbol']} are unavailable."
            )

    benchmark_observations = observed_close[BENCHMARK_TICKER].dropna()
    if benchmark_observations.empty:
        raise PerformanceDataUnavailableError(
            f"{BENCHMARK_NAME} returned no usable observations."
        )
    latest_benchmark_date = benchmark_observations.index[-1].date()
    if (today - latest_benchmark_date).days > _MAX_DATA_STALENESS_DAYS:
        raise PerformanceDataUnavailableError(
            f"{BENCHMARK_NAME} data is more than "
            f"{_MAX_DATA_STALENESS_DAYS} days stale."
        )

    def _observation_timestamps(frame: pd.DataFrame) -> pd.DataFrame:
        timestamps = pd.DataFrame(index=frame.index)
        index_series = pd.Series(frame.index, index=frame.index)
        for ticker in frame.columns:
            timestamps[ticker] = index_series.where(
                frame[ticker].notna()
            ).ffill()
        return timestamps

    close = observed_close.ffill()
    adjusted_close = observed_adjusted_close.ffill()
    observation_timestamps = _observation_timestamps(observed_close)
    adjusted_observation_timestamps = _observation_timestamps(
        observed_adjusted_close
    )

    benchmark_days = [
        timestamp
        for timestamp in benchmark_observations.index
        if start <= timestamp.date() <= today
    ]
    if not benchmark_days:
        return PerformanceResponse(
            period=period,
            start_date=start,
            data=[],
            warnings=warnings,
        )

    index_by_date = {
        timestamp.date(): timestamp
        for timestamp in observed_close.index
    }
    valuation_days = set(benchmark_days)
    start_timestamp = index_by_date.get(start)
    if start_timestamp is not None:
        valuation_days.add(start_timestamp)
    tx_by_date: dict[date, list[dict]] = defaultdict(list)
    for transaction in transactions:
        transaction_day = transaction["date"]
        effective_day = transaction_day
        is_position_change = (
            transaction["transaction_type"] in _POSITION_INCREASE_TYPES
            or transaction["transaction_type"] in _POSITION_DECREASE_TYPES
        ) and abs(float(transaction["quantity"])) > _POSITION_EPSILON
        if is_position_change and start <= transaction_day <= today:
            yf_symbol = sym_to_yf[transaction["symbol"]]
            is_synthetic = str(transaction.get("notes", "")).startswith(
                "Opening balance"
            )
            timestamp = index_by_date.get(transaction_day)
            has_symbol_observation = (
                timestamp is not None
                and yf_symbol in observed_close.columns
                and not pd.isna(observed_close.at[timestamp, yf_symbol])
            )
            if not has_symbol_observation and is_synthetic:
                prior_candidates = [
                    candidate
                    for candidate in observed_close.index
                    if candidate.date() <= transaction_day
                    and yf_symbol in observed_close.columns
                    and not pd.isna(observed_close.at[candidate, yf_symbol])
                ]
                prior_timestamp = (
                    prior_candidates[-1] if prior_candidates else None
                )
                prior_is_fresh = (
                    prior_timestamp is not None
                    and (
                        transaction_day - prior_timestamp.date()
                    ).days <= _MAX_DATA_STALENESS_DAYS
                )
                timestamp = (
                    prior_timestamp if prior_is_fresh else None
                )
                if timestamp is None:
                    raise PerformanceDataUnavailableError(
                        f"Historical prices for {transaction['symbol']} are "
                        "unavailable at its holding snapshot."
                    )
            elif not has_symbol_observation:
                raise PerformanceDataUnavailableError(
                    f"The recorded {transaction['symbol']} position change on "
                    f"{transaction_day.isoformat()} has no matching market close."
                )
            if timestamp is not None:
                effective_day = timestamp.date()
                valuation_days.add(timestamp)
        tx_by_date[effective_day].append(transaction)

    positions: dict[str, float] = defaultdict(float)
    tx_dates_sorted = sorted(tx_by_date.keys())
    tx_idx = 0
    valuation_days = sorted(valuation_days)
    benchmark_day_set = set(benchmark_days)

    def _data_value_at(
        data: pd.DataFrame,
        observed_at_data: pd.DataFrame,
        ticker: str,
        timestamp,
    ) -> float:
        if ticker not in data.columns:
            raise PerformanceDataUnavailableError(
                f"Historical data for {ticker} is unavailable."
            )
        value = data.at[timestamp, ticker]
        observed_at = observed_at_data.at[timestamp, ticker]
        if pd.isna(value) or pd.isna(observed_at):
            raise PerformanceDataUnavailableError(
                f"Historical data for {ticker} is incomplete."
            )
        age_days = (timestamp.date() - observed_at.date()).days
        if age_days > _MAX_DATA_STALENESS_DAYS:
            raise PerformanceDataUnavailableError(
                f"Historical data for {ticker} is more than "
                f"{_MAX_DATA_STALENESS_DAYS} days stale."
            )
        return float(value)

    def _market_value_at(ticker: str, timestamp) -> float:
        return _data_value_at(
            close,
            observation_timestamps,
            ticker,
            timestamp,
        )

    def _adjusted_value_at(ticker: str, timestamp) -> float:
        return _data_value_at(
            adjusted_close,
            adjusted_observation_timestamps,
            ticker,
            timestamp,
        )

    def _fx_rate_at(currency: str, timestamp) -> float:
        if currency == PERFORMANCE_CURRENCY:
            return 1.0
        fx_ticker = fx_tickers.get(currency)
        if not fx_ticker:
            raise PerformanceDataUnavailableError(
                f"EUR/{currency} exchange-rate history is unavailable."
            )
        try:
            rate = _market_value_at(fx_ticker, timestamp)
        except PerformanceDataUnavailableError as exc:
            raise PerformanceDataUnavailableError(
                f"EUR/{currency} exchange-rate history is unavailable or stale."
            ) from exc
        if rate <= 0:
            raise PerformanceDataUnavailableError(
                f"EUR/{currency} exchange-rate history is incomplete."
            )
        return rate

    def _portfolio_value_at(timestamp, current_positions: dict[str, float]) -> float:
        val = 0.0
        for symbol, quantity in current_positions.items():
            if quantity < -_POSITION_EPSILON:
                raise PerformanceDataUnavailableError(
                    f"Recorded transactions produce a negative {symbol} position."
                )
            if quantity <= _POSITION_EPSILON:
                continue
            yf_symbol = sym_to_yf[symbol]
            try:
                price = _market_value_at(yf_symbol, timestamp)
            except PerformanceDataUnavailableError as exc:
                raise PerformanceDataUnavailableError(
                    f"Historical prices for {symbol} are unavailable or stale."
                ) from exc
            currency = symbol_currencies[symbol]
            val += price * quantity / _fx_rate_at(currency, timestamp)
        return val

    def _portfolio_return_factor(
        previous_timestamp,
        timestamp,
        current_positions: dict[str, float],
    ) -> float | None:
        previous_total = 0.0
        total_return_value = 0.0
        for symbol, quantity in current_positions.items():
            if quantity < -_POSITION_EPSILON:
                raise PerformanceDataUnavailableError(
                    f"Recorded transactions produce a negative {symbol} position."
                )
            if quantity <= _POSITION_EPSILON:
                continue
            yahoo_symbol = sym_to_yf[symbol]
            currency = symbol_currencies[symbol]
            previous_fx = _fx_rate_at(currency, previous_timestamp)
            current_fx = _fx_rate_at(currency, timestamp)
            previous_market_value = (
                _market_value_at(yahoo_symbol, previous_timestamp)
                * quantity
                / previous_fx
            )
            previous_adjusted = _adjusted_value_at(
                yahoo_symbol,
                previous_timestamp,
            )
            current_adjusted = _adjusted_value_at(yahoo_symbol, timestamp)
            if previous_adjusted <= 0:
                raise PerformanceDataUnavailableError(
                    f"Adjusted historical prices for {symbol} are invalid."
                )
            eur_return_factor = (
                current_adjusted
                / previous_adjusted
                * previous_fx
                / current_fx
            )
            previous_total += previous_market_value
            total_return_value += previous_market_value * eur_return_factor
        if previous_total <= _POSITION_EPSILON:
            return None
        return total_return_value / previous_total

    daily_records: list[dict[str, Any]] = []
    previous_timestamp = None

    for ts in valuation_days:
        day = ts.date()
        period_return_factor = (
            _portfolio_return_factor(previous_timestamp, ts, positions)
            if previous_timestamp is not None
            else None
        )

        # Apply all transactions up to and including this day
        while tx_idx < len(tx_dates_sorted) and tx_dates_sorted[tx_idx] <= day:
            for t in tx_by_date[tx_dates_sorted[tx_idx]]:
                qty = float(t["quantity"])
                if t["transaction_type"] in _POSITION_INCREASE_TYPES:
                    positions[t["symbol"]] += qty
                elif t["transaction_type"] in _POSITION_DECREASE_TYPES:
                    positions[t["symbol"]] -= qty
            tx_idx += 1

        # Compute value AFTER transactions
        portfolio_value = _portfolio_value_at(ts, positions)
        benchmark_value = _market_value_at(BENCHMARK_TICKER, ts)
        benchmark_eur = benchmark_value / _fx_rate_at("USD", ts)

        daily_records.append({
            "day": day,
            "portfolio_value": portfolio_value,
            "benchmark_eur": benchmark_eur,
            "period_return_factor": period_return_factor,
            "is_benchmark_day": ts in benchmark_day_set,
        })
        previous_timestamp = ts

    # Pass 2: Chain TWRR
    data_points: list[PerformanceDataPoint] = []
    first_sp500_eur: float | None = None
    twrr_cumulative: float = 1.0
    started = False

    for rec in daily_records:
        pv = rec["portfolio_value"]
        benchmark_eur = rec["benchmark_eur"]

        if not started:
            if pv > 0:
                started = True
                first_sp500_eur = benchmark_eur
                data_points.append(
                    PerformanceDataPoint(
                        date=rec["day"],
                        portfolio_return_pct=0.0,
                        sp500_return_pct=0.0,
                        portfolio_value_eur=round(pv, 2),
                    )
                )
            continue

        period_return_factor = rec["period_return_factor"]
        if period_return_factor is not None:
            twrr_cumulative *= period_return_factor

        if first_sp500_eur is None or first_sp500_eur == 0:
            continue

        port_ret = (twrr_cumulative - 1) * 100
        sp_ret = (benchmark_eur / first_sp500_eur - 1) * 100

        if rec["is_benchmark_day"]:
            data_points.append(
                PerformanceDataPoint(
                    date=rec["day"],
                    portfolio_return_pct=round(port_ret, 2),
                    sp500_return_pct=round(sp_ret, 2),
                    portfolio_value_eur=round(pv, 2),
                )
            )

    return PerformanceResponse(
        period=period,
        start_date=start,
        data=data_points,
        warnings=warnings,
    )


async def _upsert_performance_cache(
    db: AsyncSession,
    cache_key: str,
    value: str,
    expires_at: datetime,
) -> None:
    """Atomically insert or replace a performance cache entry."""
    from sqlalchemy import func
    from app.models.cache import CacheEntry

    dialect_name = db.get_bind().dialect.name
    values = {
        "key": cache_key,
        "value": value,
        "expires_at": expires_at,
    }
    if dialect_name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    elif dialect_name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:
        raise RuntimeError(
            f"Performance cache upserts do not support {dialect_name}."
        )

    statement = insert(CacheEntry).values(**values)
    statement = statement.on_conflict_do_update(
        index_elements=[CacheEntry.key],
        set_={
            "value": value,
            "expires_at": expires_at,
            "updated_at": func.now(),
        },
    )
    await db.execute(statement)


async def compute_performance_comparison(
    db: AsyncSession,
    period: str = "1y",
) -> PerformanceResponse:
    """Return portfolio vs S&P 500 performance data, with persistent DB caching."""
    from app.models.cache import CacheEntry

    cache_key = f"{_PERFORMANCE_CACHE_PREFIX}{period.lower()}"
    now = time.time()

    # Load all transactions
    stmt = select(Transaction).order_by(Transaction.date.asc())
    result = await db.execute(stmt)
    txs = list(result.scalars().all())

    tx_dicts = [
        {
            "account_id": str(t.account_id),
            "symbol": t.symbol,
            "date": t.date,
            "quantity": float(t.quantity),
            "total_eur": float(t.total_eur),
            "transaction_type": t.transaction_type.value,
            "currency": t.currency,
            "notes": t.notes or "",
        }
        for t in txs
    ]
    statement_snapshot_by_account: dict[str, date] = {}
    for transaction in tx_dicts:
        snapshot_date = _statement_snapshot_date(transaction["notes"])
        if snapshot_date is None:
            continue
        account_id = transaction["account_id"]
        statement_snapshot_by_account[account_id] = max(
            statement_snapshot_by_account.get(account_id, snapshot_date),
            snapshot_date,
        )

    # Load holdings for currency info and to detect missing transactions
    h_result = await db.execute(select(Holding))
    holdings = list(h_result.scalars().all())
    h_dicts = [
        {
            "account_id": str(h.account_id),
            "symbol": h.symbol,
            "currency": h.currency,
            "total_quantity": float(h.total_quantity),
            "total_cost_eur": float(h.total_cost_eur),
            "snapshot_date": (
                getattr(h, "snapshot_date", None)
                or statement_snapshot_by_account.get(str(h.account_id))
                or (h.created_at.date() if h.created_at else date.today())
            ),
        }
        for h in holdings
    ]
    source_fingerprint = _performance_source_fingerprint(tx_dicts, h_dicts)

    # Validate cached responses against the current portfolio source data so
    # imports, edits, and deletes cannot leave a stale chart for two hours.
    cached_mem = _performance_cache.get(cache_key)
    if (
        cached_mem
        and cached_mem[1] == source_fingerprint
        and (now - cached_mem[0]) < _CACHE_TTL
    ):
        return cached_mem[2]

    stmt = select(CacheEntry).where(CacheEntry.key == cache_key)
    cached_db = (await db.execute(stmt)).scalar_one_or_none()
    if cached_db and cached_db.expires_at > datetime.utcnow():
        try:
            data = json.loads(cached_db.value)
            if data.get("source_fingerprint") == source_fingerprint:
                response = PerformanceResponse(
                    period=data["period"],
                    start_date=date.fromisoformat(data["start_date"]),
                    benchmark_name=data.get("benchmark_name", BENCHMARK_NAME),
                    benchmark_ticker=data.get("benchmark_ticker", BENCHMARK_TICKER),
                    currency=data.get("currency", PERFORMANCE_CURRENCY),
                    methodology=data.get("methodology", PERFORMANCE_METHODOLOGY),
                    warnings=data.get("warnings", []),
                    data=[PerformanceDataPoint(**dp) for dp in data["data"]],
                )
                _performance_cache[cache_key] = (
                    now,
                    source_fingerprint,
                    response,
                )
                return response
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            logger.warning("Ignoring invalid performance cache %s: %s", cache_key, exc)

    # Run blocking yfinance work in a thread
    response = await asyncio.to_thread(
        _compute_performance_sync,
        tx_dicts,
        h_dicts,
        period.lower(),
    )

    # Store in memory cache
    _performance_cache[cache_key] = (now, source_fingerprint, response)

    # Persist to DB cache (2-hour TTL)
    cache_data = json.dumps({
        "source_fingerprint": source_fingerprint,
        "period": response.period,
        "start_date": response.start_date.isoformat(),
        "benchmark_name": response.benchmark_name,
        "benchmark_ticker": response.benchmark_ticker,
        "currency": response.currency,
        "methodology": response.methodology,
        "warnings": response.warnings,
        "data": [
            {
                "date": dp.date.isoformat() if isinstance(dp.date, date) else dp.date,
                "portfolio_return_pct": dp.portfolio_return_pct,
                "sp500_return_pct": dp.sp500_return_pct,
                "portfolio_value_eur": dp.portfolio_value_eur,
            }
            for dp in response.data
        ],
    })
    expires = datetime.utcnow() + timedelta(hours=2)
    await _upsert_performance_cache(
        db,
        cache_key,
        cache_data,
        expires,
    )
    await db.flush()

    return response
