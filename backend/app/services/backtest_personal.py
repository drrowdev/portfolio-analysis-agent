"""Personal transaction-ledger backtest for the locked price-only signal."""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

import pandas as pd

from app.services import tax as tax_math
from app.services.backtest_engine import (
    _AlignedPrices,
    _finite_positive,
    _signal_snapshot,
    _xnys_sessions,
)
from app.services.backtest_spec import BacktestDataError, LockedBacktestInputs
from app.services.cost_basis import acquisition_unit_cost_eur
from app.services.portfolio import (
    PerformanceDataUnavailableError,
    _adjust_holdings_for_splits,
    _deduplicate_split_events,
    _is_provider_normalized_split_adjustment,
    _split_factor_after,
    _statement_snapshot_date,
)


_BUY_TYPES = {"buy", "espp_purchase"}
_SELL_TYPES = {"sell", "espp_sale"}
_POSITION_TYPES = _BUY_TYPES | _SELL_TYPES
_SUPPORTED_TAX_TREATMENTS = {"deferred"}
_EPSILON = Decimal("0.000001")


@dataclass
class _OpenLot:
    account_id: str
    symbol: str
    tax_treatment: str
    purchase_date: date
    original_quantity: Decimal
    remaining_quantity: Decimal
    price_eur: Decimal
    unit_basis_eur: Decimal
    allocated_buy_fee_eur: Decimal


@dataclass
class _Cohort:
    account_id: str
    symbol: str
    tax_treatment: str
    purchase_date: date
    exit_date: date
    quantity: Decimal
    entry_price_eur: Decimal
    unit_basis_eur: Decimal
    buy_fee_eur: Decimal
    sell_fee_eur: Decimal
    realized: bool
    signal_passed: bool = False
    entry_notional_eur: float = 0.0
    baseline_growth: float = 0.0
    benchmark_growth: float = 0.0
    overlay_growth: float = 0.0
    baseline_gain_eur: float = 0.0
    overlay_gain_eur: float = 0.0
    baseline_tax_eur: float = 0.0
    overlay_tax_eur: float = 0.0
    baseline_exit_fee_eur: float = 0.0
    overlay_entry_fee_eur: float = 0.0
    overlay_exit_fee_eur: float = 0.0
    baseline_end_value_eur: float = 0.0
    overlay_end_value_eur: float = 0.0


def _normalize_personal_ledger_for_splits(
    *,
    accounts: list[dict[str, Any]],
    holdings: list[dict[str, Any]],
    transactions: list[dict[str, Any]],
    split_events: pd.DataFrame,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    supported_account_ids = {
        str(account["id"])
        for account in accounts
        if account["tax_treatment"] in _SUPPORTED_TAX_TREATMENTS
        and account.get("account_type") != "crypto"
    }
    supported_transactions = [
        row
        for row in transactions
        if str(row["account_id"]) in supported_account_ids
    ]
    supported_holdings = [
        {
            **row,
            "snapshot_date": (
                date.fromisoformat(row["snapshot_date"])
                if isinstance(row.get("snapshot_date"), str)
                else row.get("snapshot_date")
            ),
        }
        for row in holdings
        if str(row["account_id"]) in supported_account_ids
    ]
    position_symbols = {
        str(row["symbol"])
        for row in supported_transactions
        if str(row["transaction_type"]) in _POSITION_TYPES
    }
    missing_split_history = sorted(position_symbols - set(split_events.columns))
    if missing_split_history:
        raise BacktestDataError(
            "Stock-split history is unavailable for "
            + ", ".join(missing_split_history)
            + "."
        )
    split_events = _deduplicate_split_events(split_events)
    symbol_mapping = {symbol: symbol for symbol in position_symbols}
    try:
        normalized_holdings = _adjust_holdings_for_splits(
            supported_holdings,
            supported_transactions,
            split_events,
            symbol_mapping,
        )
    except (KeyError, PerformanceDataUnavailableError) as exc:
        raise BacktestDataError(
            "The holdings ledger cannot be normalized for stock splits."
        ) from exc

    normalized_transactions: list[dict[str, Any]] = []
    for transaction in supported_transactions:
        if _is_provider_normalized_split_adjustment(transaction):
            continue
        normalized = dict(transaction)
        if str(transaction["transaction_type"]) in _POSITION_TYPES:
            notes = str(transaction.get("notes") or "")
            basis_date = (
                _statement_snapshot_date(notes)
                if notes.startswith("Imported from Nordnet lot export")
                else None
            ) or transaction["date"]
            split_factor = _split_factor_after(
                str(transaction["symbol"]),
                basis_date,
                split_events,
            )
            if split_factor <= 0:
                raise BacktestDataError(
                    f"{transaction['symbol']} has an invalid stock-split factor."
                )
            normalized["quantity"] = (
                Decimal(str(transaction.get("quantity") or 0))
                * Decimal(str(split_factor))
            )
            normalized["price_eur"] = (
                Decimal(str(transaction.get("price_eur") or 0))
                / Decimal(str(split_factor))
            )
        normalized_transactions.append(normalized)

    unsupported_transactions = [
        row
        for row in transactions
        if str(row["account_id"]) not in supported_account_ids
    ]
    unsupported_holdings = [
        row
        for row in holdings
        if str(row["account_id"]) not in supported_account_ids
    ]
    return (
        [*normalized_holdings, *unsupported_holdings],
        [*normalized_transactions, *unsupported_transactions],
    )


def audit_personal_ledger(
    *,
    accounts: list[dict[str, Any]],
    holdings: list[dict[str, Any]],
    transactions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Measure ledger consistency without inferring gaps from importer notes."""
    holdings_by_position: dict[tuple[str, str], Decimal] = defaultdict(
        lambda: Decimal("0")
    )
    for holding in holdings:
        holdings_by_position[
            (str(holding["account_id"]), str(holding["symbol"]))
        ] += Decimal(str(holding["quantity"]))

    transactions_by_account: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for transaction in transactions:
        transactions_by_account[str(transaction["account_id"])].append(transaction)

    account_reports: list[dict[str, Any]] = []
    global_blockers: list[str] = []
    for account in accounts:
        account_id = str(account["id"])
        rows = sorted(
            transactions_by_account.get(account_id, []),
            key=lambda row: (
                row["date"],
                str(row.get("id", "")),
            ),
        )
        quantities: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        unmatched_sells: set[str] = set()
        source_markers: set[str] = set()
        transaction_types: dict[str, int] = defaultdict(int)
        for row in rows:
            transaction_type = str(row["transaction_type"])
            transaction_types[transaction_type] += 1
            notes = str(row.get("notes") or "")
            if "Imported from Nordnet lot export" in notes:
                source_markers.add("nordnet_open_lot_export")
            elif notes.startswith("Fidelity "):
                source_markers.add("fidelity_statement")
            elif notes:
                source_markers.add("manual_or_other")
            else:
                source_markers.add("unmarked")
            quantity = Decimal(str(row.get("quantity") or 0))
            symbol = str(row["symbol"])
            if transaction_type in _BUY_TYPES:
                quantities[symbol] += quantity
            elif transaction_type in _SELL_TYPES:
                quantities[symbol] -= quantity
                if quantities[symbol] < -_EPSILON:
                    unmatched_sells.add(symbol)

        positions = {
            symbol
            for position_account, symbol in holdings_by_position
            if position_account == account_id
        } | set(quantities)
        mismatches = [
            {
                "symbol": symbol,
                "ledger_quantity": str(quantities[symbol]),
                "holding_quantity": str(
                    holdings_by_position.get((account_id, symbol), Decimal("0"))
                ),
            }
            for symbol in sorted(positions)
            if abs(
                quantities[symbol]
                - holdings_by_position.get((account_id, symbol), Decimal("0"))
            )
            > _EPSILON
        ]
        blockers: list[str] = []
        if unmatched_sells:
            blockers.append(
                "Sales exceed recorded FIFO acquisitions for "
                + ", ".join(sorted(unmatched_sells))
                + "."
            )
        if mismatches:
            blockers.append("Transaction quantities do not reconcile to holdings.")
        if account["tax_treatment"] == "standard":
            blockers.append(
                "Standard taxable accounts are blocked because adjusted-close "
                "returns include dividends but the locked backtest has no "
                "point-in-time dividend-tax input."
            )
        elif account["tax_treatment"] not in _SUPPORTED_TAX_TREATMENTS:
            blockers.append(
                f"{account['tax_treatment']} tax treatment is unsupported by "
                "the personal backtest."
            )
        if account.get("account_type") == "crypto":
            blockers.append("Crypto is outside the equity benchmark backtest scope.")
        if not rows:
            blockers.append("The account has no recorded transactions.")
        if blockers:
            global_blockers.extend(
                f"{account['name']}: {blocker}" for blocker in blockers
            )
        account_reports.append(
            {
                "account_id": account_id,
                "account_name": account["name"],
                "account_type": account["account_type"],
                "tax_treatment": account["tax_treatment"],
                "transaction_count": len(rows),
                "transaction_date_start": (
                    min(row["date"] for row in rows).isoformat() if rows else None
                ),
                "transaction_date_end": (
                    max(row["date"] for row in rows).isoformat() if rows else None
                ),
                "transaction_types": dict(sorted(transaction_types.items())),
                "source_markers": sorted(source_markers),
                "unmatched_sell_symbols": sorted(unmatched_sells),
                "quantity_mismatches": mismatches,
                "eligible": not blockers,
                "blockers": blockers,
            }
        )
    return {
        "can_backtest_all_accounts": not global_blockers,
        "accounts": account_reports,
        "blockers": global_blockers,
        "methodology": (
            "Completeness is accepted from the user-provided ledger and tested by "
            "FIFO non-negativity plus current-holding reconciliation. Importer note "
            "text is provenance only and never proves that history is incomplete."
        ),
    }


def _build_cohorts(
    transactions: list[dict[str, Any]],
    *,
    end_date: date,
    eligible_accounts: set[str],
) -> list[_Cohort]:
    lots: dict[tuple[str, str], list[_OpenLot]] = defaultdict(list)
    cohorts: list[_Cohort] = []
    rows = sorted(
        (
            row
            for row in transactions
            if str(row["account_id"]) in eligible_accounts
            and str(row["transaction_type"]) in _POSITION_TYPES
            and row["date"] <= end_date
        ),
        key=lambda row: (row["date"], str(row.get("id", ""))),
    )
    for row in rows:
        account_id = str(row["account_id"])
        symbol = str(row["symbol"])
        key = (account_id, symbol)
        transaction_type = str(row["transaction_type"])
        quantity = Decimal(str(row.get("quantity") or 0))
        price_eur = Decimal(str(row.get("price_eur") or 0))
        fees = Decimal(str(row.get("fees") or 0))
        if quantity <= 0 or price_eur <= 0:
            raise BacktestDataError(
                f"{symbol} has a non-positive transaction quantity or EUR price."
            )
        if transaction_type in _BUY_TYPES:
            lots[key].append(
                _OpenLot(
                    account_id=account_id,
                    symbol=symbol,
                    tax_treatment=str(row["tax_treatment"]),
                    purchase_date=row["date"],
                    original_quantity=quantity,
                    remaining_quantity=quantity,
                    price_eur=price_eur,
                    unit_basis_eur=acquisition_unit_cost_eur(
                        price_eur,
                        quantity,
                        fees,
                    ),
                    allocated_buy_fee_eur=fees,
                )
            )
            continue

        remaining = quantity
        while remaining > _EPSILON and lots[key]:
            lot = lots[key][0]
            take = min(remaining, lot.remaining_quantity)
            buy_fee = (
                lot.allocated_buy_fee_eur
                * take
                / lot.original_quantity
            )
            sell_fee = fees * take / quantity
            cohorts.append(
                _Cohort(
                    account_id=account_id,
                    symbol=symbol,
                    tax_treatment=lot.tax_treatment,
                    purchase_date=lot.purchase_date,
                    exit_date=row["date"],
                    quantity=take,
                    entry_price_eur=lot.price_eur,
                    unit_basis_eur=lot.unit_basis_eur,
                    buy_fee_eur=buy_fee,
                    sell_fee_eur=sell_fee,
                    realized=True,
                )
            )
            lot.remaining_quantity -= take
            remaining -= take
            if lot.remaining_quantity <= _EPSILON:
                lots[key].pop(0)
        if remaining > _EPSILON:
            raise BacktestDataError(
                f"Recorded sales exceed FIFO acquisitions for {symbol}."
            )
    for open_lots in lots.values():
        for lot in open_lots:
            if lot.remaining_quantity <= _EPSILON:
                continue
            cohorts.append(
                _Cohort(
                    account_id=lot.account_id,
                    symbol=lot.symbol,
                    tax_treatment=lot.tax_treatment,
                    purchase_date=lot.purchase_date,
                    exit_date=end_date,
                    quantity=lot.remaining_quantity,
                    entry_price_eur=lot.price_eur,
                    unit_basis_eur=lot.unit_basis_eur,
                    buy_fee_eur=(
                        lot.allocated_buy_fee_eur
                        * lot.remaining_quantity
                        / lot.original_quantity
                    ),
                    sell_fee_eur=Decimal("0"),
                    realized=False,
                )
            )
    return cohorts


def _last_close_before(
    calendar: pd.DatetimeIndex,
    value: date,
) -> pd.Timestamp | None:
    eligible = calendar[calendar < pd.Timestamp(value)]
    return eligible[-1] if len(eligible) else None


def _first_close_on_or_after(
    calendar: pd.DatetimeIndex,
    value: date,
) -> pd.Timestamp | None:
    eligible = calendar[calendar >= pd.Timestamp(value)]
    return eligible[0] if len(eligible) else None


def _cohort_taxable_gain(
    cohort: _Cohort,
    *,
    sell_price_eur: float,
    sell_fee_eur: float,
    unit_basis_eur: float,
    quantity: Decimal | None = None,
) -> float:
    taxable_quantity = quantity if quantity is not None else cohort.quantity
    result = tax_math.compute(
        [
            tax_math.TaxLot(
                quantity=taxable_quantity,
                cost_per_share_eur=Decimal(str(unit_basis_eur)),
                over_10_years=tax_math.held_at_least_10_years(
                    cohort.purchase_date,
                    cohort.exit_date,
                ),
            )
        ],
        Decimal(str(sell_price_eur)),
        Decimal(str(sell_fee_eur)),
        taxable_quantity,
    )
    return float(result.optimum_gain_eur)


def _apply_annual_tax(cohorts: list[_Cohort]) -> None:
    baseline_income: dict[int, float] = defaultdict(float)
    overlay_income: dict[int, float] = defaultdict(float)
    baseline_liability: dict[int, float] = defaultdict(float)
    overlay_liability: dict[int, float] = defaultdict(float)
    for cohort in sorted(
        cohorts,
        key=lambda value: (
            value.exit_date,
            value.account_id,
            value.symbol,
            value.purchase_date,
        ),
    ):
        if cohort.tax_treatment == "deferred":
            continue
        year = cohort.exit_date.year
        previous = baseline_liability[year]
        baseline_income[year] += cohort.baseline_gain_eur
        current = float(
            tax_math.bracket_total_tax(
                Decimal(str(baseline_income[year]))
            )
        )
        cohort.baseline_tax_eur = current - previous
        baseline_liability[year] = current

        previous = overlay_liability[year]
        overlay_income[year] += cohort.overlay_gain_eur
        current = float(
            tax_math.bracket_total_tax(
                Decimal(str(overlay_income[year]))
            )
        )
        cohort.overlay_tax_eur = current - previous
        overlay_liability[year] = current


def _period_for_purchase(
    purchase_date: date,
    specification: dict[str, Any],
) -> str | None:
    for name, values in specification["periods"].items():
        if name == "warmup":
            continue
        if date.fromisoformat(values["start"]) <= purchase_date <= date.fromisoformat(
            values["end"]
        ):
            return name
    return None


def _cohort_metrics(
    cohorts: list[_Cohort],
    *,
    period: str,
) -> dict[str, Any]:
    if not cohorts:
        return {
            "period": period,
            "cohort_count": 0,
            "entry_notional_eur": 0.0,
        }
    total_notional = sum(value.entry_notional_eur for value in cohorts)
    baseline_end = sum(value.baseline_end_value_eur for value in cohorts)
    overlay_end = sum(value.overlay_end_value_eur for value in cohorts)
    active_returns = [
        (
            value.overlay_end_value_eur - value.baseline_end_value_eur
        )
        / value.entry_notional_eur
        for value in cohorts
        if value.entry_notional_eur > 0
    ]
    passing = [value for value in cohorts if value.signal_passed]
    failing = [value for value in cohorts if not value.signal_passed]

    def _weighted_asset_minus_benchmark(rows: list[_Cohort]) -> float | None:
        notional = sum(row.entry_notional_eur for row in rows)
        if notional <= 0:
            return None
        return (
            sum(
                row.entry_notional_eur
                * (row.baseline_growth - row.benchmark_growth)
                for row in rows
            )
            / notional
            * 100
        )

    return {
        "period": period,
        "cohort_count": len(cohorts),
        "realized_cohort_count": sum(value.realized for value in cohorts),
        "entry_notional_eur": total_notional,
        "signal_pass_rate_pct": len(passing) / len(cohorts) * 100,
        "baseline_net_return_pct": (baseline_end / total_notional - 1) * 100,
        "overlay_net_return_pct": (overlay_end / total_notional - 1) * 100,
        "overlay_net_value_add_pct": (
            (overlay_end - baseline_end) / total_notional * 100
        ),
        "positive_value_add_rate_pct": (
            sum(value > 0 for value in active_returns) / len(active_returns) * 100
        ),
        "baseline_tax_eur": sum(value.baseline_tax_eur for value in cohorts),
        "overlay_tax_eur": sum(value.overlay_tax_eur for value in cohorts),
        "passing_cohort_asset_minus_benchmark_pct": (
            _weighted_asset_minus_benchmark(passing)
        ),
        "failing_cohort_asset_minus_benchmark_pct": (
            _weighted_asset_minus_benchmark(failing)
        ),
    }


def run_personal_transaction_backtest(
    *,
    prices_eur: pd.DataFrame,
    split_events: pd.DataFrame,
    price_data_hash: str,
    price_data_source: str,
    locked: LockedBacktestInputs,
    policy: Any,
    accounts: list[dict[str, Any]],
    holdings: list[dict[str, Any]],
    transactions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Evaluate the locked signal on FIFO-reconstructed personal purchase cohorts."""
    holdings, transactions = _normalize_personal_ledger_for_splits(
        accounts=accounts,
        holdings=holdings,
        transactions=transactions,
        split_events=split_events,
    )
    coverage = audit_personal_ledger(
        accounts=accounts,
        holdings=holdings,
        transactions=transactions,
    )
    eligible_accounts = {
        report["account_id"]
        for report in coverage["accounts"]
        if report["eligible"]
    }
    if not eligible_accounts:
        return {
            "status": "blocked",
            "track": "actual_portfolio",
            "spec_version": locked.specification["spec_version"],
            "specification_hash": locked.specification_hash,
            "coverage": coverage,
            "blockers": coverage["blockers"] or [
                "No supported, reconciled account ledger is available."
            ],
            "historical_evidence_is_proof_of_future_alpha": False,
        }
    specification = locked.specification
    benchmark = specification["benchmark"]["ticker"]
    maximum_age = int(specification["execution"]["maximum_price_age_calendar_days"])
    aligned = _AlignedPrices(prices_eur, benchmark, maximum_age)
    holdout_end = date.fromisoformat(
        specification["periods"]["holdout"]["end"]
    )
    raw_benchmark = aligned.raw_series(benchmark)
    valid_benchmark = raw_benchmark[
        raw_benchmark.map(_finite_positive)
        & (raw_benchmark.index <= pd.Timestamp(holdout_end))
    ]
    if valid_benchmark.empty:
        raise BacktestDataError("Personal-track benchmark prices are empty.")
    expected_sessions = _xnys_sessions(
        pd.Timestamp(valid_benchmark.index.min()).date(),
        holdout_end,
    )
    missing_sessions = expected_sessions[
        ~raw_benchmark.reindex(expected_sessions).map(_finite_positive)
    ]
    if len(missing_sessions):
        return {
            "status": "blocked",
            "track": "actual_portfolio",
            "spec_version": specification["spec_version"],
            "specification_hash": locked.specification_hash,
            "coverage": coverage,
            "data_manifest": {
                "price_data_source": price_data_source,
                "price_data_hash": price_data_hash,
                "registered_end": holdout_end.isoformat(),
                "observed_end": (
                    pd.Timestamp(valid_benchmark.index.max()).date().isoformat()
                ),
                "missing_benchmark_session_count": len(missing_sessions),
                "missing_benchmark_session_preview": [
                    value.date().isoformat() for value in missing_sessions[:10]
                ],
            },
            "blockers": [
                "Personal-track benchmark prices omit one or more NYSE sessions, "
                "including coverage required through the registered holdout end."
            ],
            "historical_evidence_is_proof_of_future_alpha": False,
        }
    registered_closes = aligned.calendar[
        aligned.calendar <= pd.Timestamp(holdout_end)
    ]
    valuation_close = registered_closes[-1] if len(registered_closes) else None
    if (
        valuation_close is None
        or (holdout_end - valuation_close.date()).days > maximum_age
    ):
        return {
            "status": "blocked",
            "track": "actual_portfolio",
            "spec_version": specification["spec_version"],
            "specification_hash": locked.specification_hash,
            "coverage": coverage,
            "data_manifest": {
                "price_data_source": price_data_source,
                "price_data_hash": price_data_hash,
                "registered_end": holdout_end.isoformat(),
                "observed_end": (
                    aligned.calendar[-1].date().isoformat()
                    if len(aligned.calendar)
                    else None
                ),
            },
            "blockers": [
                "Personal-track prices do not cover the registered holdout end."
            ],
            "historical_evidence_is_proof_of_future_alpha": False,
        }
    available_end = valuation_close.date()
    cohorts = _build_cohorts(
        transactions,
        end_date=available_end,
        eligible_accounts=eligible_accounts,
    )
    if not cohorts:
        return {
            "status": "blocked",
            "track": "actual_portfolio",
            "spec_version": specification["spec_version"],
            "specification_hash": locked.specification_hash,
            "coverage": coverage,
            "blockers": ["No supported acquisition cohorts are available."],
            "historical_evidence_is_proof_of_future_alpha": False,
        }
    transaction_cost_bps = getattr(
        policy,
        "estimated_transaction_cost_bps",
        None,
    )
    if transaction_cost_bps is None:
        return {
            "status": "blocked",
            "track": "actual_portfolio",
            "spec_version": specification["spec_version"],
            "specification_hash": locked.specification_hash,
            "coverage": coverage,
            "blockers": ["The transaction-cost policy is not configured."],
            "historical_evidence_is_proof_of_future_alpha": False,
        }
    cost_rate = float(transaction_cost_bps) / 10_000
    personal_settings = specification["personal_portfolio_track"]
    active_overlay = float(personal_settings["active_overlay_pct"]) / 100
    preserved_exposure = (
        float(personal_settings["preserved_actual_exposure_pct"]) / 100
    )
    if (
        active_overlay < 0
        or preserved_exposure < 0
        or not math.isclose(
            active_overlay + preserved_exposure,
            1.0,
            rel_tol=0,
            abs_tol=1e-12,
        )
    ):
        raise BacktestDataError(
            "The personal overlay and preserved exposure must sum to 100%."
        )

    for cohort in cohorts:
        signal_at = _last_close_before(aligned.calendar, cohort.purchase_date)
        entry_at = _first_close_on_or_after(
            aligned.calendar,
            cohort.purchase_date,
        )
        exit_at = _first_close_on_or_after(aligned.calendar, cohort.exit_date)
        if signal_at is None or entry_at is None or exit_at is None:
            raise BacktestDataError(
                f"Market dates cannot bracket the {cohort.symbol} cohort."
            )
        scores = _signal_snapshot(
            aligned,
            signal_at=signal_at,
            candidates={cohort.symbol},
            benchmark=benchmark,
            specification=specification,
        )
        cohort.signal_passed = cohort.symbol in scores
        entry_asset = aligned.level(cohort.symbol, entry_at)
        exit_asset = aligned.level(cohort.symbol, exit_at)
        entry_benchmark = aligned.level(benchmark, entry_at)
        exit_benchmark = aligned.level(benchmark, exit_at)
        cohort.baseline_growth = exit_asset / entry_asset
        cohort.benchmark_growth = exit_benchmark / entry_benchmark
        cohort.overlay_growth = (
            cohort.baseline_growth
            if cohort.signal_passed
            else (
                preserved_exposure * cohort.baseline_growth
                + active_overlay * cohort.benchmark_growth
            )
        )
        quantity = float(cohort.quantity)
        gross_entry = quantity * float(cohort.entry_price_eur)
        cohort.entry_notional_eur = gross_entry
        baseline_exit_gross = gross_entry * cohort.baseline_growth
        baseline_sell_fee = (
            float(cohort.sell_fee_eur)
            if cohort.realized
            else baseline_exit_gross * cost_rate
        )
        cohort.baseline_exit_fee_eur = baseline_sell_fee
        cohort.baseline_gain_eur = _cohort_taxable_gain(
            cohort,
            sell_price_eur=baseline_exit_gross / quantity,
            sell_fee_eur=baseline_sell_fee,
            unit_basis_eur=float(cohort.unit_basis_eur),
        )
        if cohort.signal_passed:
            cohort.overlay_gain_eur = cohort.baseline_gain_eur
        else:
            preserved_quantity = cohort.quantity * Decimal(
                str(preserved_exposure)
            )
            active_entry_gross = gross_entry * active_overlay
            active_quantity = Decimal(
                str(active_entry_gross / entry_benchmark)
            )
            preserved_exit_gross = (
                gross_entry
                * preserved_exposure
                * cohort.baseline_growth
            )
            active_exit_gross = active_entry_gross * cohort.benchmark_growth
            preserved_buy_fee = float(cohort.buy_fee_eur) * preserved_exposure
            active_buy_fee = active_entry_gross * cost_rate
            preserved_sell_fee = baseline_sell_fee * preserved_exposure
            active_sell_fee = active_exit_gross * cost_rate
            cohort.overlay_entry_fee_eur = (
                preserved_buy_fee + active_buy_fee
            )
            cohort.overlay_exit_fee_eur = (
                preserved_sell_fee + active_sell_fee
            )
            preserved_gain = (
                _cohort_taxable_gain(
                    cohort,
                    sell_price_eur=preserved_exit_gross
                    / float(preserved_quantity),
                    sell_fee_eur=preserved_sell_fee,
                    unit_basis_eur=float(cohort.unit_basis_eur),
                    quantity=preserved_quantity,
                )
                if preserved_quantity > 0
                else 0.0
            )
            active_gain = (
                _cohort_taxable_gain(
                    cohort,
                    sell_price_eur=active_exit_gross / float(active_quantity),
                    sell_fee_eur=active_sell_fee,
                    unit_basis_eur=(
                        active_entry_gross + active_buy_fee
                    )
                    / float(active_quantity),
                    quantity=active_quantity,
                )
                if active_quantity > 0
                else 0.0
            )
            cohort.overlay_gain_eur = preserved_gain + active_gain

    _apply_annual_tax(cohorts)
    for cohort in cohorts:
        gross_entry = cohort.entry_notional_eur
        baseline_exit = gross_entry * cohort.baseline_growth
        cohort.baseline_end_value_eur = (
            baseline_exit
            - float(cohort.buy_fee_eur)
            - cohort.baseline_exit_fee_eur
            - cohort.baseline_tax_eur
        )
        if cohort.signal_passed:
            cohort.overlay_end_value_eur = cohort.baseline_end_value_eur
        else:
            overlay_exit = gross_entry * cohort.overlay_growth
            cohort.overlay_end_value_eur = (
                overlay_exit
                - cohort.overlay_entry_fee_eur
                - cohort.overlay_exit_fee_eur
                - cohort.overlay_tax_eur
            )

    cohorts_by_period: dict[str, list[_Cohort]] = defaultdict(list)
    for cohort in cohorts:
        period = _period_for_purchase(cohort.purchase_date, specification)
        if period:
            cohorts_by_period[period].append(cohort)
    split_results = [
        _cohort_metrics(cohorts_by_period.get(period, []), period=period)
        for period in ("development", "validation", "holdout")
    ]
    exclusions = [
        report
        for report in coverage["accounts"]
        if not report["eligible"]
    ]
    return {
        "status": "completed_with_exclusions" if exclusions else "completed",
        "track": "actual_portfolio",
        "spec_version": specification["spec_version"],
        "specification_hash": locked.specification_hash,
        "data_manifest": {
            "price_data_source": price_data_source,
            "price_data_hash": price_data_hash,
            "transaction_count": len(transactions),
            "supported_account_count": len(eligible_accounts),
            "registered_end": holdout_end.isoformat(),
            "valuation_close": available_end.isoformat(),
        },
        "coverage": coverage,
        "split_results": split_results,
        "cohort_count": len(cohorts),
        "promotion_eligible": False,
        "promotion_blockers": [
            "Personal FIFO cohorts overlap and are applicability evidence, not an "
            "independent portfolio-level alpha estimate.",
            "Point-in-time universe evidence and forward shadow confirmation are "
            "both required.",
            *(
                ["One or more accounts were excluded from the personal track."]
                if exclusions
                else []
            ),
        ],
        "assumptions": [
            "Signals use only closes strictly before each recorded acquisition date.",
            "Actual FIFO sale dates define cohort exits but are not visible to the signal.",
            "Open cohorts use a terminal-liquidation tax estimate at the registered end date.",
            "A failed or unavailable signal preserves the registered actual exposure "
            "and replaces only the registered active sleeve with the benchmark.",
            "Recorded fees apply proportionally to preserved actual exposure; the "
            "configured basis-point cost applies only to the benchmark sleeve.",
            "Recorded transaction completeness is user-authoritative unless FIFO or "
            "holding reconciliation demonstrates a specific inconsistency.",
        ],
        "historical_evidence_is_proof_of_future_alpha": False,
    }
