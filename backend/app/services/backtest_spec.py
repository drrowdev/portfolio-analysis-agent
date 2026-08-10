"""Locked alpha-backtest specification and point-in-time universe inputs."""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd


class BacktestDataError(RuntimeError):
    """Raised when a backtest input cannot support reproducible evidence."""


_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "backtests"
_SPEC_PATH = _DATA_DIR / "alpha_momentum_trend_v1.json"
_SPEC_HASH_PATH = _DATA_DIR / "alpha_momentum_trend_v1.sha256"
_MEMBERSHIP_PATH = _DATA_DIR / "sp500_membership_intervals.csv"
_MEMBERSHIP_PROVENANCE_PATH = _DATA_DIR / "sp500_membership_provenance.json"


@dataclass(frozen=True)
class MembershipInterval:
    ticker: str
    start_date: date
    end_date: date | None

    def contains(self, value: date) -> bool:
        return self.start_date <= value and (
            self.end_date is None or value <= self.end_date
        )


@dataclass(frozen=True)
class LockedBacktestInputs:
    specification: dict[str, Any]
    specification_hash: str
    membership_provenance: dict[str, Any]
    membership_hash: str
    membership_intervals: tuple[MembershipInterval, ...]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_expected_hash(path: Path) -> str:
    try:
        expected, filename = path.read_text(encoding="utf-8").strip().split(maxsplit=1)
    except (OSError, ValueError) as exc:
        raise BacktestDataError(f"Invalid hash manifest: {path.name}.") from exc
    if Path(filename).name != _SPEC_PATH.name or len(expected) != 64:
        raise BacktestDataError(f"Invalid hash manifest: {path.name}.")
    return expected.lower()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BacktestDataError(f"Cannot load {path.name}.") from exc
    if not isinstance(payload, dict):
        raise BacktestDataError(f"{path.name} must contain a JSON object.")
    return payload


def load_locked_specification() -> tuple[dict[str, Any], str]:
    expected = _read_expected_hash(_SPEC_HASH_PATH)
    actual = sha256_file(_SPEC_PATH)
    if actual != expected:
        raise BacktestDataError(
            "The locked alpha-backtest specification hash does not match."
        )
    specification = _load_json(_SPEC_PATH)
    if specification.get("status") != "locked":
        raise BacktestDataError("The alpha-backtest specification is not locked.")
    return specification, actual


def load_membership_intervals() -> tuple[
    dict[str, Any], str, tuple[MembershipInterval, ...]
]:
    provenance = _load_json(_MEMBERSHIP_PROVENANCE_PATH)
    expected = str(provenance.get("sha256", "")).lower()
    actual = sha256_file(_MEMBERSHIP_PATH)
    if not expected or actual != expected:
        raise BacktestDataError(
            "The point-in-time membership file does not match its provenance hash."
        )

    intervals: list[MembershipInterval] = []
    try:
        with _MEMBERSHIP_PATH.open(encoding="utf-8", newline="") as source:
            reader = csv.DictReader(source)
            if reader.fieldnames != ["ticker", "start_date", "end_date"]:
                raise BacktestDataError(
                    "Membership data must contain ticker,start_date,end_date."
                )
            for row in reader:
                ticker = row["ticker"].strip()
                start_date = date.fromisoformat(row["start_date"])
                end_date = (
                    date.fromisoformat(row["end_date"])
                    if row["end_date"].strip()
                    else None
                )
                if not ticker or (end_date is not None and end_date < start_date):
                    raise BacktestDataError("Membership data contains an invalid row.")
                intervals.append(
                    MembershipInterval(
                        ticker=ticker,
                        start_date=start_date,
                        end_date=end_date,
                    )
                )
    except (OSError, ValueError, KeyError) as exc:
        raise BacktestDataError("Cannot parse point-in-time membership data.") from exc
    if not intervals:
        raise BacktestDataError("Point-in-time membership data is empty.")
    return provenance, actual, tuple(intervals)


def load_locked_backtest_inputs() -> LockedBacktestInputs:
    specification, specification_hash = load_locked_specification()
    provenance, membership_hash, intervals = load_membership_intervals()
    return LockedBacktestInputs(
        specification=specification,
        specification_hash=specification_hash,
        membership_provenance=provenance,
        membership_hash=membership_hash,
        membership_intervals=intervals,
    )


def members_on(
    intervals: tuple[MembershipInterval, ...],
    as_of: date,
) -> set[str]:
    return {interval.ticker for interval in intervals if interval.contains(as_of)}


def load_eur_price_csv(path: Path) -> tuple[pd.DataFrame, str]:
    """Load immutable adjusted-close levels already converted to EUR."""
    if not path.is_file():
        raise BacktestDataError(f"Market-data file does not exist: {path}.")
    data_hash = sha256_file(path)
    try:
        raw = pd.read_csv(path)
    except Exception as exc:
        raise BacktestDataError("Cannot parse the configured market-data CSV.") from exc
    required = {"date", "ticker", "adjusted_close_eur"}
    missing = required - set(raw.columns)
    if missing:
        raise BacktestDataError(
            "Market-data CSV is missing columns: " + ", ".join(sorted(missing))
        )
    frame = raw.loc[:, ["date", "ticker", "adjusted_close_eur"]].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["ticker"] = frame["ticker"].astype(str).str.strip()
    frame["adjusted_close_eur"] = pd.to_numeric(
        frame["adjusted_close_eur"], errors="coerce"
    )
    if (
        frame["date"].isna().any()
        or (frame["ticker"] == "").any()
        or frame["adjusted_close_eur"].isna().any()
        or (frame["adjusted_close_eur"] <= 0).any()
        or frame.duplicated(["date", "ticker"]).any()
    ):
        raise BacktestDataError(
            "Market-data CSV contains invalid, non-positive, or duplicate observations."
        )
    prices = (
        frame.pivot(index="date", columns="ticker", values="adjusted_close_eur")
        .sort_index()
        .astype(float)
    )
    prices.index = pd.DatetimeIndex(prices.index).tz_localize(None)
    return prices, data_hash
