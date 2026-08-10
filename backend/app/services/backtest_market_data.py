"""Market-data adapters for backtests."""

from __future__ import annotations

import hashlib
from datetime import date, timedelta
from typing import Any

import pandas as pd
import yfinance as yf

from app.services.backtest_spec import BacktestDataError
from app.services.market_data import _yf_symbol


def _extract_adjusted_close(
    raw: pd.DataFrame,
    fallback_ticker: str,
) -> pd.DataFrame:
    if isinstance(raw.columns, pd.MultiIndex):
        if "Adj Close" in raw.columns.get_level_values(0):
            frame = raw["Adj Close"]
        elif "Adj Close" in raw.columns.get_level_values(-1):
            frame = raw.xs("Adj Close", axis=1, level=-1)
        else:
            return pd.DataFrame(index=raw.index)
    elif "Adj Close" in raw.columns:
        frame = raw[["Adj Close"]].rename(columns={"Adj Close": fallback_ticker})
    else:
        return pd.DataFrame(index=raw.index)
    if isinstance(frame, pd.Series):
        frame = frame.to_frame(name=fallback_ticker)
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(-1)
    frame.columns = [str(column) for column in frame.columns]
    frame.index = pd.to_datetime(frame.index).tz_localize(None).normalize()
    return frame.sort_index().apply(pd.to_numeric, errors="coerce")


def hash_price_frame(prices: pd.DataFrame) -> str:
    canonical = (
        prices.sort_index()
        .sort_index(axis=1)
        .rename_axis("date")
        .to_csv(
            date_format="%Y-%m-%d",
            float_format="%.12g",
            na_rep="",
            lineterminator="\n",
        )
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _extract_stock_splits(
    raw: pd.DataFrame,
    yahoo_symbols: dict[str, str],
) -> pd.DataFrame:
    if isinstance(raw.columns, pd.MultiIndex):
        if "Stock Splits" in raw.columns.get_level_values(0):
            frame = raw["Stock Splits"]
        elif "Stock Splits" in raw.columns.get_level_values(-1):
            frame = raw.xs("Stock Splits", axis=1, level=-1)
        else:
            raise BacktestDataError(
                "Yahoo returned no stock-split history for the personal track."
            )
    elif "Stock Splits" in raw.columns and len(yahoo_symbols) == 1:
        original_symbol = next(iter(yahoo_symbols))
        frame = raw[["Stock Splits"]].rename(
            columns={"Stock Splits": original_symbol}
        )
        frame.index = pd.to_datetime(frame.index).tz_localize(None).normalize()
        return frame.sort_index().apply(pd.to_numeric, errors="coerce")
    else:
        raise BacktestDataError(
            "Yahoo returned no stock-split history for the personal track."
        )
    if isinstance(frame, pd.Series):
        frame = frame.to_frame()
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(-1)
    frame.columns = [str(column) for column in frame.columns]
    missing = sorted(
        original
        for original, yahoo_symbol in yahoo_symbols.items()
        if yahoo_symbol not in frame
    )
    if missing:
        raise BacktestDataError(
            "Yahoo returned no stock-split history for "
            + ", ".join(missing)
            + "."
        )
    output = pd.DataFrame(
        {
            original: pd.to_numeric(frame[yahoo_symbol], errors="coerce")
            for original, yahoo_symbol in yahoo_symbols.items()
        }
    )
    output.index = pd.to_datetime(output.index).tz_localize(None).normalize()
    return output.sort_index()


def download_personal_eur_prices(
    *,
    transactions: list[dict[str, Any]],
    benchmark: str,
    end_date: date,
) -> tuple[pd.DataFrame, pd.DataFrame, str, str]:
    """Download one immutable-in-the-run Yahoo snapshot for the personal track."""
    position_rows = [
        row
        for row in transactions
        if str(row["transaction_type"])
        in {"buy", "sell", "espp_purchase", "espp_sale"}
        and row["date"] <= end_date
    ]
    if not position_rows:
        raise BacktestDataError("No position-changing transactions are available.")
    symbol_currencies: dict[str, str] = {}
    for row in position_rows:
        symbol = str(row["symbol"])
        currency = str(row["currency"]).upper()
        existing = symbol_currencies.setdefault(symbol, currency)
        if existing != currency:
            raise BacktestDataError(
                f"{symbol} has transactions in multiple currencies."
            )

    start_date = min(row["date"] for row in position_rows) - timedelta(days=550)
    yahoo_symbols = {symbol: _yf_symbol(symbol) for symbol in symbol_currencies}
    fx_tickers = {
        currency: f"EUR{currency}=X"
        for currency in set(symbol_currencies.values()) | {"USD"}
        if currency != "EUR"
    }
    tickers = list(
        dict.fromkeys(
            [*yahoo_symbols.values(), benchmark, *fx_tickers.values()]
        )
    )
    try:
        raw = yf.download(
            tickers,
            start=start_date.isoformat(),
            end=(end_date + timedelta(days=5)).isoformat(),
            auto_adjust=False,
            actions=True,
            progress=False,
        )
    except Exception as exc:
        raise BacktestDataError(
            "Historical personal-track market data is temporarily unavailable."
        ) from exc
    if raw.empty:
        raise BacktestDataError(
            "Historical personal-track market data returned no observations."
        )
    adjusted = _extract_adjusted_close(raw, tickers[0])
    if adjusted.empty:
        raise BacktestDataError(
            "Historical personal-track data has no adjusted closes."
        )

    output: dict[str, pd.Series] = {}
    for symbol, yahoo_symbol in yahoo_symbols.items():
        if yahoo_symbol not in adjusted:
            raise BacktestDataError(f"Yahoo has no adjusted-close column for {symbol}.")
        native = adjusted[yahoo_symbol]
        currency = symbol_currencies[symbol]
        if currency == "EUR":
            output[symbol] = native
            continue
        fx_ticker = fx_tickers[currency]
        if fx_ticker not in adjusted:
            raise BacktestDataError(f"Yahoo has no EUR/{currency} FX history.")
        aligned_fx = adjusted[fx_ticker].reindex(
            native.index,
            method="ffill",
            tolerance=pd.Timedelta(days=4),
        )
        output[symbol] = native / aligned_fx

    if benchmark not in adjusted:
        raise BacktestDataError(f"Yahoo has no adjusted-close column for {benchmark}.")
    usd_fx_ticker = fx_tickers["USD"]
    if usd_fx_ticker not in adjusted:
        raise BacktestDataError("Yahoo has no EUR/USD FX history.")
    benchmark_fx = adjusted[usd_fx_ticker].reindex(
        adjusted.index,
        method="ffill",
        tolerance=pd.Timedelta(days=4),
    )
    output[benchmark] = adjusted[benchmark] / benchmark_fx
    prices = pd.DataFrame(output).sort_index()
    prices = prices.loc[:pd.Timestamp(end_date)]
    split_events = _extract_stock_splits(raw, yahoo_symbols)
    split_events = split_events.loc[:pd.Timestamp(end_date)]
    data_hash = hashlib.sha256(
        (
            f"prices:{hash_price_frame(prices)}\n"
            f"splits:{hash_price_frame(split_events)}"
        ).encode("utf-8")
    ).hexdigest()
    source = (
        "Yahoo Finance adjusted-close and split runtime snapshot for personal, "
        "non-commercial use; "
        f"query={start_date.isoformat()}..{end_date.isoformat()}"
    )
    return prices, split_events, data_hash, source
