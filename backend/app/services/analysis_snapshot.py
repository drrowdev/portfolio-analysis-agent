from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.account import Account
from app.models.goal import InvestmentGoal
from app.models.holding import Holding
from app.models.strategy import Strategy
from app.models.transaction import Transaction, TransactionType
from app.models.user_settings import UserSetting
from app.schemas.analysis import (
    AccountSnapshot,
    AnalysisMetrics,
    AnalysisSnapshot,
    CapitalIncomeSnapshot,
    DataQualityIssue,
    DataQualityState,
    GoalSnapshot,
    HoldingSnapshot,
    OpenTaxLotSnapshot,
    StrategySnapshot,
)
from app.services import capital_income, symbol_metadata
from app.services.analysis_metrics import (
    calculate_concentration,
    calculate_performance_risk,
    calculate_sector_exposure,
    calculate_ytd_turnover,
)
from app.services.analysis_baselines import evaluate_baselines
from app.services.portfolio import (
    PerformanceDataUnavailableError,
    compute_performance_comparison,
)
from app.services.proof_of_value import get_policy
from app.services.cost_basis import acquisition_unit_cost_eur


_MONEY = Decimal("0.01")
_PCT = Decimal("0.01")
_BUY_TYPES = {TransactionType.buy, TransactionType.espp_purchase}
_SELL_TYPES = {TransactionType.sell, TransactionType.espp_sale}
_INCOME_TYPES = _BUY_TYPES | _SELL_TYPES | {TransactionType.dividend}


def _money(value: Decimal) -> Decimal:
    return value.quantize(_MONEY, rounding=ROUND_HALF_UP)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _coverage_gaps(
    periods: list[tuple[date, date]],
    required_start: date,
    required_end: date,
) -> list[tuple[date, date]]:
    """Return uncovered dates after merging overlapping or adjacent intervals."""
    clipped = sorted(
        {
            (max(start, required_start), min(end, required_end))
            for start, end in periods
            if start <= end and end >= required_start and start <= required_end
        }
    )
    if not clipped:
        return [(required_start, required_end)]

    gaps: list[tuple[date, date]] = []
    coverage_start, coverage_end = clipped[0]
    if coverage_start > required_start:
        gaps.append((required_start, coverage_start - timedelta(days=1)))

    for period_start, period_end in clipped[1:]:
        if period_start > coverage_end + timedelta(days=1):
            gaps.append(
                (coverage_end + timedelta(days=1), period_start - timedelta(days=1))
            )
        coverage_end = max(coverage_end, period_end)

    if coverage_end < required_end:
        gaps.append((coverage_end + timedelta(days=1), required_end))
    return gaps


def _replay_open_tax_lots(
    transactions: list[Transaction],
) -> tuple[list[OpenTaxLotSnapshot], dict[tuple[str, str], Decimal]]:
    """Replay transaction history into the acquisition lots still held."""
    lots: dict[tuple[str, str], list[list[object]]] = defaultdict(list)
    unmatched_sells: dict[tuple[str, str], Decimal] = defaultdict(
        lambda: Decimal("0")
    )
    for transaction in transactions:
        key = (str(transaction.account_id), transaction.symbol)
        quantity = transaction.quantity or Decimal("0")
        if transaction.transaction_type in _BUY_TYPES:
            if quantity > 0:
                unit_cost = acquisition_unit_cost_eur(
                    transaction.price_eur or Decimal("0"),
                    quantity,
                    getattr(transaction, "fees", None) or Decimal("0"),
                )
                lots[key].append(
                    [quantity, unit_cost, transaction.date]
                )
            continue
        if transaction.transaction_type not in _SELL_TYPES or quantity <= 0:
            continue

        remaining = quantity
        while remaining > 0 and lots[key]:
            lot_quantity = lots[key][0][0]
            if not isinstance(lot_quantity, Decimal):
                raise TypeError("Tax lot quantity must be Decimal")
            if lot_quantity <= remaining:
                remaining -= lot_quantity
                lots[key].pop(0)
            else:
                lots[key][0][0] = lot_quantity - remaining
                remaining = Decimal("0")
        if remaining > 0:
            unmatched_sells[key] += remaining

    snapshots: list[OpenTaxLotSnapshot] = []
    for (account_id, symbol), rows in sorted(lots.items()):
        for quantity, cost, purchase_date in rows:
            if not isinstance(quantity, Decimal):
                raise TypeError("Tax lot quantity must be Decimal")
            if not isinstance(cost, Decimal):
                raise TypeError("Tax lot cost must be Decimal")
            if not isinstance(purchase_date, date):
                raise TypeError("Tax lot purchase date must be date")
            snapshots.append(
                OpenTaxLotSnapshot(
                    account_id=account_id,
                    symbol=symbol,
                    purchase_date=purchase_date,
                    quantity=quantity,
                    cost_per_share_eur=cost,
                )
            )
    return snapshots, dict(unmatched_sells)


def build_open_tax_lots(
    transactions: list[Transaction],
) -> list[OpenTaxLotSnapshot]:
    """Return open FIFO lots; snapshot construction separately validates coverage."""
    return _replay_open_tax_lots(transactions)[0]


def _capital_income_snapshot(
    transactions: list[Transaction],
    treatment_by_account: dict[str, str],
    year: int,
) -> CapitalIncomeSnapshot:
    relevant = [
        capital_income.IncomeTxn(
            account_id=str(transaction.account_id),
            tax_treatment=treatment_by_account.get(
                str(transaction.account_id), "standard"
            ),
            symbol=transaction.symbol,
            txn_type=transaction.transaction_type.value,
            date=transaction.date,
            quantity=transaction.quantity or Decimal("0"),
            price_eur=transaction.price_eur or Decimal("0"),
            total_eur=transaction.total_eur or Decimal("0"),
            fees=transaction.fees or Decimal("0"),
        )
        for transaction in transactions
        if transaction.transaction_type in _INCOME_TYPES
    ]
    summary = capital_income.compute_capital_income(relevant, year)
    return CapitalIncomeSnapshot(
        year=summary.year,
        taxable_gains_eur=_money(summary.taxable_gains_eur),
        taxable_dividends_eur=_money(summary.taxable_dividends_eur),
        combined_taxable_eur=_money(summary.combined_taxable_eur),
        estimated_tax_eur=_money(summary.estimated_tax_eur),
        remaining_at_low_rate_eur=_money(summary.remaining_at_low_rate_eur),
        amount_over_threshold_eur=_money(summary.amount_over_threshold_eur),
    )


async def build_analysis_snapshot(db: AsyncSession) -> AnalysisSnapshot:
    """Build one reproducible, data-quality-aware input for investment analysis."""
    now = datetime.now(timezone.utc)
    policy = await get_policy(db)
    issues: list[DataQualityIssue] = []
    if not policy.is_complete:
        issues.append(
            DataQualityIssue(
                code="policy_incomplete",
                severity="blocking",
                message=(
                    "Complete your investment goal, risk limits, and trading-cost "
                    "assumptions in Advanced evidence before relying on guidance."
                ),
            )
        )
    account_result = await db.execute(
        select(Account)
        .options(selectinload(Account.holdings))
        .order_by(Account.id)
    )
    account_rows = list(account_result.scalars().all())
    if not account_rows:
        issues.append(
            DataQualityIssue(
                code="portfolio_empty",
                severity="blocking",
                message="No investment accounts are available for analysis.",
            )
        )

    cash_result = await db.execute(
        select(UserSetting).where(UserSetting.key == "cash_available")
    )
    cash_setting = cash_result.scalar_one_or_none()
    try:
        cash = Decimal(cash_setting.value) if cash_setting else Decimal("0")
    except InvalidOperation:
        cash = Decimal("0")
        issues.append(
            DataQualityIssue(
                code="invalid_cash_setting",
                severity="blocking",
                message="The cash_available setting is not a valid number.",
            )
        )

    raw_holdings: list[tuple[Account, Holding, Decimal | None]] = []
    invested_value = Decimal("0")
    for account in account_rows:
        if (
            account.account_type.value == "osakesaastotili"
            and account.ost_lifetime_deposits is None
        ):
            issues.append(
                DataQualityIssue(
                    code="missing_ost_deposits",
                    severity="blocking",
                    message=(
                        f"{account.name} is missing lifetime OST deposits, so the "
                        "remaining statutory deposit capacity cannot be verified."
                    ),
                )
            )
        for holding in sorted(
            account.holdings,
            key=lambda item: (item.symbol, str(item.id)),
        ):
            value = holding.current_value_eur
            raw_holdings.append((account, holding, value))
            if value is not None and value > 0:
                invested_value += value

    holding_snapshots: list[HoldingSnapshot] = []
    account_snapshots: list[AccountSnapshot] = []
    position_values: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    sector_values: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    account_values: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    account_costs: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    missing_prices: list[str] = []
    missing_price_timestamps: list[str] = []
    stale_prices: list[str] = []
    missing_metadata: list[str] = []

    for account, holding, value in raw_holdings:
        account_id = str(account.id)
        account_costs[account_id] += holding.total_cost_eur
        if value is not None and value > 0:
            account_values[account_id] += value
            position_values[holding.symbol] += value

        if holding.total_quantity > 0 and (
            holding.current_price_eur is None or value is None
        ):
            missing_prices.append(holding.symbol)

        price_as_of = (
            _as_utc(holding.last_price_update)
            if holding.last_price_update is not None
            else None
        )
        if (
            holding.total_quantity > 0
            and holding.current_price_eur is not None
            and value is not None
            and price_as_of is None
        ):
            missing_price_timestamps.append(holding.symbol)
        if (
            holding.total_quantity > 0
            and price_as_of is not None
            and (now - price_as_of).total_seconds()
            > policy.price_stale_after_hours * 3600
        ):
            stale_prices.append(holding.symbol)

        metadata = symbol_metadata.sector_info(holding.symbol)
        if metadata is None:
            missing_metadata.append(holding.symbol)
            sector = None
            industry = None
            country = None
            if value is not None and value > 0:
                sector_values["Unknown"] += value
        else:
            sector = metadata["sector"]
            industry = metadata["industry"]
            country = metadata["country"]
            if value is not None and value > 0:
                sector_values[sector] += value

        weight = (
            value / invested_value * 100
            if value is not None and value > 0 and invested_value > 0
            else None
        )
        holding_snapshots.append(
            HoldingSnapshot(
                account_id=account_id,
                account_name=account.name,
                account_type=account.account_type.value,
                tax_treatment=account.tax_treatment.value,
                symbol=holding.symbol,
                instrument_name=holding.instrument_name,
                currency=holding.currency,
                quantity=holding.total_quantity,
                cost_basis_eur=_money(holding.total_cost_eur),
                current_price_eur=holding.current_price_eur,
                current_value_eur=_money(value) if value is not None else None,
                unrealized_pnl_eur=(
                    _money(holding.unrealized_pnl_eur)
                    if holding.unrealized_pnl_eur is not None
                    else None
                ),
                unrealized_pnl_pct=(
                    holding.unrealized_pnl_pct.quantize(
                        _PCT, rounding=ROUND_HALF_UP
                    )
                    if holding.unrealized_pnl_pct is not None
                    else None
                ),
                portfolio_weight_pct=(
                    weight.quantize(_PCT, rounding=ROUND_HALF_UP)
                    if weight is not None
                    else None
                ),
                sector=sector,
                industry=industry,
                country=country,
                price_as_of=price_as_of,
            )
        )

    for account in account_rows:
        account_id = str(account.id)
        account_snapshots.append(
            AccountSnapshot(
                id=account_id,
                name=account.name,
                account_type=account.account_type.value,
                tax_treatment=account.tax_treatment.value,
                currency=account.currency,
                ost_lifetime_deposits_eur=account.ost_lifetime_deposits,
                market_value_eur=_money(account_values[account_id]),
                cost_basis_eur=_money(account_costs[account_id]),
            )
        )

    if missing_prices:
        symbols = sorted(set(missing_prices))
        issues.append(
            DataQualityIssue(
                code="missing_market_prices",
                severity="blocking",
                message=(
                    "Current market prices are missing; cost basis was not used as "
                    "a substitute."
                ),
                symbols=symbols,
            )
        )
    if stale_prices:
        symbols = sorted(set(stale_prices))
        issues.append(
            DataQualityIssue(
                code="stale_market_prices",
                severity="blocking",
                message=(
                    "Market prices exceed the configured freshness limit of "
                    f"{policy.price_stale_after_hours} hours."
                ),
                symbols=symbols,
            )
        )
    if missing_price_timestamps:
        issues.append(
            DataQualityIssue(
                code="missing_price_timestamp",
                severity="blocking",
                message=(
                    "Current prices have no as-of timestamp, so their freshness "
                    "cannot be verified."
                ),
                symbols=sorted(set(missing_price_timestamps)),
            )
        )
    if missing_metadata:
        issues.append(
            DataQualityIssue(
                code="missing_sector_metadata",
                severity="blocking",
                message=(
                    "Sector concentration cannot be checked against its limit for "
                    "positions without symbol metadata."
                ),
                symbols=sorted(set(missing_metadata)),
            )
        )

    transaction_result = await db.execute(
        select(Transaction).order_by(
            Transaction.date.asc(),
            Transaction.created_at.asc(),
            Transaction.id.asc(),
        )
    )
    transactions = list(transaction_result.scalars().all())
    unverified_fx_symbols = sorted(
        {
            transaction.symbol
            for transaction in transactions
            if transaction.currency.upper() != "EUR"
            and transaction.fx_rate is None
            and (
                transaction.price_native != 0
                or transaction.total_native != 0
            )
        }
    )
    if unverified_fx_symbols:
        issues.append(
            DataQualityIssue(
                code="unverified_transaction_fx",
                severity="blocking",
                message=(
                    "Non-EUR transactions are missing verified historical FX rates; "
                    "their EUR tax basis may still contain native-currency values."
                ),
                symbols=unverified_fx_symbols,
            )
        )
    invalid_tax_basis_symbols = sorted(
        {
            transaction.symbol
            for transaction in transactions
            if transaction.transaction_type in _BUY_TYPES | _SELL_TYPES
            and transaction.quantity > 0
            and (transaction.price_eur <= 0 or transaction.total_eur <= 0)
        }
    )
    if invalid_tax_basis_symbols:
        issues.append(
            DataQualityIssue(
                code="invalid_transaction_eur_basis",
                severity="blocking",
                message=(
                    "Acquisition or sale rows have a non-positive EUR price or total, "
                    "so after-tax return cannot be reproduced."
                ),
                symbols=invalid_tax_basis_symbols,
            )
        )

    open_tax_lots, unmatched_sells = _replay_open_tax_lots(transactions)
    current_quantities: dict[tuple[str, str], Decimal] = defaultdict(
        lambda: Decimal("0")
    )
    for account, holding, _ in raw_holdings:
        current_quantities[(str(account.id), holding.symbol)] += holding.total_quantity
    lot_quantities: dict[tuple[str, str], Decimal] = defaultdict(
        lambda: Decimal("0")
    )
    for lot in open_tax_lots:
        lot_quantities[(lot.account_id, lot.symbol)] += lot.quantity

    tolerance = Decimal("0.000001")
    mismatched_lots = {
        key
        for key in current_quantities.keys() | lot_quantities.keys()
        if abs(current_quantities[key] - lot_quantities[key]) > tolerance
    }
    invalid_tax_symbols = sorted(
        {
            symbol
            for _, symbol in mismatched_lots | set(unmatched_sells)
        }
    )
    if invalid_tax_symbols:
        issues.append(
            DataQualityIssue(
                code="incomplete_tax_lots",
                severity="blocking",
                message=(
                    "FIFO acquisition lots do not reconcile to current holdings or "
                    "a sale exceeds recorded lots; after-tax trade math is unavailable."
                ),
                symbols=invalid_tax_symbols,
            )
        )
    treatment_by_account = {
        str(account.id): account.tax_treatment.value for account in account_rows
    }

    strategy_result = await db.execute(
        select(Strategy)
        .where(Strategy.is_active == True)  # noqa: E712
        .order_by(Strategy.id)
    )
    active_strategies = list(strategy_result.scalars().all())
    strategy_row = active_strategies[0] if len(active_strategies) == 1 else None
    strategy_snapshot = None
    if not active_strategies:
        issues.append(
            DataQualityIssue(
                code="missing_strategy",
                severity="blocking",
                message="No active investment strategy is configured.",
            )
        )
    elif len(active_strategies) > 1:
        issues.append(
            DataQualityIssue(
                code="multiple_active_strategies",
                severity="blocking",
                message=(
                    "More than one investment strategy is active; analysis cannot "
                    "choose a risk contract deterministically."
                ),
            )
        )
    else:
        strategy_snapshot = StrategySnapshot(
            name=strategy_row.name,
            description=strategy_row.description,
            risk_tolerance=strategy_row.risk_tolerance.value,
            target_allocation={
                key: float(value)
                for key, value in strategy_row.target_allocation.items()
            },
            rebalance_threshold_pct=strategy_row.rebalance_threshold_pct,
            tax_optimization_enabled=strategy_row.tax_optimization_enabled,
            custom_rules=strategy_row.custom_rules,
        )

    goal_result = await db.execute(
        select(InvestmentGoal)
        .where(InvestmentGoal.is_active == True)  # noqa: E712
        .order_by(InvestmentGoal.id)
    )
    goals = [
        GoalSnapshot(
            name=goal.name,
            target_amount_eur=goal.target_amount_eur,
            target_date=goal.target_date,
            assumed_annual_return_pct=goal.assumed_annual_return_pct,
        )
        for goal in goal_result.scalars().all()
    ]

    performance_metrics = None
    try:
        performance = await compute_performance_comparison(db, "1y")
        for warning in performance.warnings:
            issues.append(
                DataQualityIssue(
                    code="performance_warning",
                    severity="blocking",
                    message=warning,
                )
            )
        contains_crypto = any(
            account.account_type.value == "crypto"
            or symbol_metadata.is_crypto(holding.symbol)
            for account, holding, _ in raw_holdings
            if holding.total_quantity > 0
        )
        if contains_crypto:
            issues.append(
                DataQualityIssue(
                    code="performance_scope_incomplete",
                    severity="blocking",
                    message=(
                        "Risk and benchmark metrics exclude crypto positions and "
                        "therefore do not represent the whole portfolio."
                    ),
                )
            )
        if not performance.data:
            issues.append(
                DataQualityIssue(
                    code="performance_unavailable",
                    severity="blocking",
                    message="One-year performance contains no verified observations.",
                )
            )
        if performance.data and not performance.warnings and not contains_crypto:
            performance_metrics = calculate_performance_risk(performance)
    except PerformanceDataUnavailableError as exc:
        issues.append(
            DataQualityIssue(
                code="performance_unavailable",
                severity="blocking",
                message=str(exc),
            )
        )

    analysis_metrics = AnalysisMetrics(
        performance=performance_metrics,
        concentration=calculate_concentration(list(position_values.items())),
        sectors=calculate_sector_exposure(
            dict(sector_values),
            invested_value,
        ),
        turnover=calculate_ytd_turnover(
            year=now.year,
            traded_notionals_eur=[
                (
                    abs(transaction.total_eur)
                    if transaction.total_eur is not None
                    else abs(
                        (transaction.quantity or Decimal("0"))
                        * (transaction.price_eur or Decimal("0"))
                    )
                )
                for transaction in transactions
                if transaction.transaction_type in _BUY_TYPES | _SELL_TYPES
                and date(now.year, 1, 1) <= transaction.date <= now.date()
            ],
            portfolio_value_eur=invested_value + cash,
        ),
    )
    snapshot = AnalysisSnapshot(
        as_of=now,
        snapshot_hash="",
        policy=policy,
        data_quality=DataQualityState(
            can_recommend_trades=not any(
                issue.severity == "blocking" for issue in issues
            ),
            issues=issues,
        ),
        cash_eur=_money(cash),
        invested_value_eur=_money(invested_value),
        total_portfolio_value_eur=_money(invested_value + cash),
        accounts=account_snapshots,
        holdings=holding_snapshots,
        open_tax_lots=open_tax_lots,
        capital_income=_capital_income_snapshot(
            transactions, treatment_by_account, now.year
        ),
        strategy=strategy_snapshot,
        goals=goals,
        metrics=analysis_metrics,
        baselines=evaluate_baselines(policy, analysis_metrics),
    )
    hash_input = json.dumps(
        snapshot.model_dump(mode="json", exclude={"snapshot_hash"}),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return snapshot.model_copy(
        update={"snapshot_hash": hashlib.sha256(hash_input).hexdigest()}
    )
