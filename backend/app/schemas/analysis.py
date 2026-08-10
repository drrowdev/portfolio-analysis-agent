from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator


AnalysisMode = Literal["shadow"]
IssueSeverity = Literal["info", "warning", "blocking"]


class ProofOfValuePolicy(BaseModel):
    """Explicit objective and risk constraints for investment analysis."""

    mode: AnalysisMode = "shadow"
    benchmark_name: Literal["S&P 500 Total Return"] = "S&P 500 Total Return"
    benchmark_ticker: Literal["^SP500TR"] = "^SP500TR"
    benchmark_currency: Literal["EUR"] = "EUR"
    investment_horizon_years: int | None = Field(default=None, ge=1, le=50)
    max_drawdown_pct: Decimal | None = Field(default=None, gt=0, le=100)
    max_annualized_volatility_pct: Decimal | None = Field(
        default=None, gt=0, le=100
    )
    max_tracking_error_pct: Decimal | None = Field(default=None, gt=0, le=100)
    max_single_position_pct: Decimal | None = Field(default=None, gt=0, le=100)
    max_sector_pct: Decimal | None = Field(default=None, gt=0, le=100)
    max_annual_turnover_pct: Decimal | None = Field(default=None, gt=0, le=1000)
    estimated_transaction_cost_bps: Decimal | None = Field(
        default=None, ge=0, le=1000
    )
    minimum_expected_net_alpha_pct: Decimal | None = Field(
        default=None, ge=0, le=100
    )
    price_stale_after_hours: int = Field(default=96, ge=1, le=720)


class ProofOfValuePolicyState(ProofOfValuePolicy):
    is_complete: bool
    missing_fields: list[str]
    objective: str
    return_methodology: str


class DataQualityIssue(BaseModel):
    code: str
    severity: IssueSeverity
    message: str
    symbols: list[str] = Field(default_factory=list)


class DataQualityState(BaseModel):
    can_recommend_trades: bool
    issues: list[DataQualityIssue] = Field(default_factory=list)


class HoldingSnapshot(BaseModel):
    account_id: str
    account_name: str
    account_type: str
    tax_treatment: str
    symbol: str
    instrument_name: str
    currency: str
    quantity: Decimal
    cost_basis_eur: Decimal
    current_price_eur: Decimal | None
    current_value_eur: Decimal | None
    unrealized_pnl_eur: Decimal | None
    unrealized_pnl_pct: Decimal | None
    portfolio_weight_pct: Decimal | None
    sector: str | None
    industry: str | None
    country: str | None
    price_as_of: datetime | None


class AccountSnapshot(BaseModel):
    id: str
    name: str
    account_type: str
    tax_treatment: str
    currency: str
    ost_lifetime_deposits_eur: Decimal | None
    market_value_eur: Decimal
    cost_basis_eur: Decimal


class OpenTaxLotSnapshot(BaseModel):
    account_id: str
    symbol: str
    purchase_date: date
    quantity: Decimal
    cost_per_share_eur: Decimal


class CapitalIncomeSnapshot(BaseModel):
    year: int
    taxable_gains_eur: Decimal
    taxable_dividends_eur: Decimal
    combined_taxable_eur: Decimal
    estimated_tax_eur: Decimal
    remaining_at_low_rate_eur: Decimal
    amount_over_threshold_eur: Decimal


class GoalSnapshot(BaseModel):
    name: str
    target_amount_eur: Decimal
    target_date: date
    assumed_annual_return_pct: Decimal


class StrategySnapshot(BaseModel):
    name: str
    description: str
    risk_tolerance: str
    target_allocation: dict[str, float]
    rebalance_threshold_pct: Decimal
    tax_optimization_enabled: bool
    custom_rules: list[object] | None


class PerformanceRiskMetrics(BaseModel):
    period: str
    observations: int
    portfolio_return_pct: float | None
    benchmark_return_pct: float | None
    active_return_pct: float | None
    annualized_volatility_pct: float | None
    benchmark_annualized_volatility_pct: float | None
    tracking_error_pct: float | None
    beta: float | None
    max_drawdown_pct: float | None
    benchmark_max_drawdown_pct: float | None


class ConcentrationMetrics(BaseModel):
    invested_value_eur: Decimal
    position_count: int
    largest_position_symbol: str | None
    largest_position_pct: Decimal | None
    top_five_positions_pct: Decimal | None
    herfindahl_index: Decimal | None


class SectorExposure(BaseModel):
    sector: str
    value_eur: Decimal
    weight_pct: Decimal


class TurnoverMetrics(BaseModel):
    year: int
    traded_notional_eur: Decimal
    portfolio_value_eur: Decimal
    ytd_turnover_pct: Decimal | None
    methodology: str


class AnalysisMetrics(BaseModel):
    performance: PerformanceRiskMetrics | None
    concentration: ConcentrationMetrics
    sectors: list[SectorExposure]
    turnover: TurnoverMetrics | None = None


class BaselineSignal(BaseModel):
    code: str
    status: Literal["pass", "breach", "unavailable"]
    metric_value: Decimal | None = None
    policy_limit: Decimal | None = None
    message: str


class BaselineComparison(BaseModel):
    hold_current_return_pct: Decimal | None
    benchmark_return_pct: Decimal | None
    historical_active_return_pct: Decimal | None
    deterministic_policy_status: Literal[
        "within_limits", "review_required", "blocked"
    ]
    signals: list[BaselineSignal]
    methodology: str


class AnalysisSnapshot(BaseModel):
    schema_version: str = "1.0"
    as_of: datetime
    snapshot_hash: str
    policy: ProofOfValuePolicyState
    data_quality: DataQualityState
    cash_eur: Decimal
    invested_value_eur: Decimal
    total_portfolio_value_eur: Decimal
    accounts: list[AccountSnapshot]
    holdings: list[HoldingSnapshot]
    open_tax_lots: list[OpenTaxLotSnapshot]
    capital_income: CapitalIncomeSnapshot
    strategy: StrategySnapshot | None
    goals: list[GoalSnapshot]
    metrics: AnalysisMetrics
    baselines: BaselineComparison


class GuidanceHealth(BaseModel):
    status: Literal["on_track", "review", "blocked"]
    title: str
    detail: str
    origin: Literal["rule"] = "rule"


class GuidanceAction(BaseModel):
    status: Literal["no_action", "review", "blocked"]
    decision: Literal["hold", "abstain"]
    title: str
    detail: str
    origin: Literal["rule", "quant_model"]
    provenance: str
    as_of: datetime


class GuidanceException(BaseModel):
    code: str
    severity: IssueSeverity
    title: str
    detail: str
    origin: Literal["rule"] = "rule"


class GuidanceTaxCostFacts(BaseModel):
    year: int
    tracked_taxable_income_eur: Decimal
    estimated_tax_eur: Decimal
    remaining_at_low_rate_eur: Decimal
    amount_over_threshold_eur: Decimal
    ytd_turnover_pct: Decimal | None
    transaction_cost_assumption_bps: Decimal | None
    quantified_savings_eur: Decimal | None = None
    detail: str


class GuidancePassiveBaseline(BaseModel):
    period: str
    index_name: str
    index_ticker: str
    currency: str
    status: Literal["available", "unavailable"]
    portfolio_return_pct: float | None
    index_return_pct: float | None
    active_return_pct: float | None
    comparison_basis: str
    excluded_from_comparison: list[str]
    investable_comparator_status: Literal["available", "not_configured"]
    investable_comparator_name: str | None = None
    investable_comparator_ticker: str | None = None
    investable_comparator_return_pct: float | None = None
    investable_comparator_message: str


class GuidanceBrief(BaseModel):
    schema_version: str = "1.0"
    as_of: datetime
    snapshot_hash: str
    health: GuidanceHealth
    best_action: GuidanceAction
    current_exceptions: list[GuidanceException]
    tax_and_cost: GuidanceTaxCostFacts
    passive_baseline: GuidancePassiveBaseline
    snapshot: AnalysisSnapshot
    disclaimer: str


class GuidanceRefreshStep(BaseModel):
    key: Literal["market_prices", "guidance"]
    status: Literal["completed", "blocked"]
    detail: str
    updated_count: int | None = None


class GuidanceRefreshResponse(BaseModel):
    guidance: GuidanceBrief
    steps: list[GuidanceRefreshStep]


RecommendationDecision = Literal[
    "buy", "sell", "hold", "rebalance", "monitor", "abstain"
]
RecommendationPriority = Literal["high", "medium", "low"]
RecommendationConfidence = Literal["high", "medium", "low"]
RecommendationUrgency = Literal["immediate", "soon", "routine", "none"]


class AnalysisSource(BaseModel):
    name: str
    url: str
    date: str


class AnalysisInsight(BaseModel):
    title: str
    detail: str
    severity: Literal["info", "warning", "action"]
    sources: list[AnalysisSource] = Field(default_factory=list)


class AnalysisRecommendation(BaseModel):
    """A traceable shadow decision; trade decisions require executable fields."""

    action: str
    rationale: str
    account_type: str = ""
    priority: RecommendationPriority
    decision: RecommendationDecision
    confidence: RecommendationConfidence
    urgency: RecommendationUrgency
    candidate_id: str | None = None
    candidate_group_id: str | None = None
    candidate_objective: Literal["return_seeking", "risk_enforcement"] | None = None
    symbol: str | None = None
    account_id: str | None = None
    quantity: Decimal | None = Field(default=None, gt=0)
    amount_eur: Decimal | None = Field(default=None, gt=0)
    timeframe: str | None = None
    valid_until: date | None = None
    expected_return_low_pct: Decimal | None = None
    expected_return_high_pct: Decimal | None = None
    expected_net_alpha_pct: Decimal | None = None
    expected_alpha_horizon_days: Literal[1, 5, 20, 60] | None = None
    downside_pct: Decimal | None = None
    estimated_transaction_cost_eur: Decimal | None = Field(default=None, ge=0)
    estimated_tax_impact_eur: Decimal | None = None
    risk_impact: str | None = None
    reference_price_eur: Decimal | None = Field(default=None, gt=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    execution_assumption: Literal["cash", "benchmark"] | None = None
    trigger_conditions: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_trade_fields(self) -> "AnalysisRecommendation":
        if self.decision not in {"buy", "sell", "rebalance"}:
            forbidden = {
                "candidate_id": self.candidate_id,
                "candidate_group_id": self.candidate_group_id,
                "candidate_objective": self.candidate_objective,
                "quantity": self.quantity,
                "amount_eur": self.amount_eur,
                "expected_return_low_pct": self.expected_return_low_pct,
                "expected_return_high_pct": self.expected_return_high_pct,
                "expected_net_alpha_pct": self.expected_net_alpha_pct,
                "expected_alpha_horizon_days": self.expected_alpha_horizon_days,
                "downside_pct": self.downside_pct,
                "estimated_transaction_cost_eur": (
                    self.estimated_transaction_cost_eur
                ),
                "estimated_tax_impact_eur": self.estimated_tax_impact_eur,
                "risk_impact": self.risk_impact,
                "reference_price_eur": self.reference_price_eur,
                "currency": self.currency,
                "execution_assumption": self.execution_assumption,
            }
            supplied = [field for field, value in forbidden.items() if value is not None]
            if supplied:
                raise ValueError(
                    "Non-trade decisions cannot contain executable fields: "
                    + ", ".join(supplied)
                )
            return self
        missing: list[str] = []
        if not self.candidate_id:
            missing.append("candidate_id")
        if not self.candidate_group_id:
            missing.append("candidate_group_id")
        if self.candidate_objective is None:
            missing.append("candidate_objective")
        if not self.symbol:
            missing.append("symbol")
        if not self.account_id:
            missing.append("account_id")
        if not self.account_type:
            missing.append("account_type")
        if self.quantity is None and self.amount_eur is None:
            missing.append("quantity or amount_eur")
        if not self.timeframe:
            missing.append("timeframe")
        if self.valid_until is None:
            missing.append("valid_until")
        if self.candidate_objective == "return_seeking":
            if self.expected_net_alpha_pct is None:
                missing.append("expected_net_alpha_pct")
            if self.expected_alpha_horizon_days is None:
                missing.append("expected_alpha_horizon_days")
            if self.downside_pct is None:
                missing.append("downside_pct")
        elif self.candidate_objective == "risk_enforcement":
            unsupported_forecasts = {
                "expected_return_low_pct": self.expected_return_low_pct,
                "expected_return_high_pct": self.expected_return_high_pct,
                "expected_net_alpha_pct": self.expected_net_alpha_pct,
                "expected_alpha_horizon_days": self.expected_alpha_horizon_days,
                "downside_pct": self.downside_pct,
            }
            supplied_forecasts = [
                field
                for field, value in unsupported_forecasts.items()
                if value is not None
            ]
            if supplied_forecasts:
                raise ValueError(
                    "Risk-enforcement candidates cannot contain return forecasts: "
                    + ", ".join(supplied_forecasts)
                )
        if self.estimated_transaction_cost_eur is None:
            missing.append("estimated_transaction_cost_eur")
        if self.estimated_tax_impact_eur is None:
            missing.append("estimated_tax_impact_eur")
        if self.risk_impact is None:
            missing.append("risk_impact")
        if self.reference_price_eur is None:
            missing.append("reference_price_eur")
        if self.currency is None:
            missing.append("currency")
        if self.execution_assumption is None:
            missing.append("execution_assumption")
        if missing:
            raise ValueError(
                "Trade recommendations require deterministic fields: "
                + ", ".join(missing)
            )
        return self


class CandidateGenerationResult(BaseModel):
    status: Literal["no_action", "candidates", "blocked"]
    recommendations: list[AnalysisRecommendation] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    current_invested_value_eur: Decimal
    projected_invested_value_eur: Decimal
    current_ytd_turnover_pct: Decimal | None
    projected_ytd_turnover_pct: Decimal | None
    methodology: str


class ModelAnalysisResult(BaseModel):
    summary: str
    insights: list[AnalysisInsight] = Field(default_factory=list)
    recommendations: list[AnalysisRecommendation] = Field(default_factory=list)
    risk_factors: list[str] = Field(default_factory=list)


class AnalysisRunMeta(BaseModel):
    mode: AnalysisMode = "shadow"
    as_of: datetime
    snapshot_hash: str | None
    input_hash: str | None = None
    model: str
    prompt_version: str
    can_recommend_trades: bool
    data_quality_issues: list[str] = Field(default_factory=list)


class AnalysisResult(ModelAnalysisResult):
    meta: AnalysisRunMeta


class ShadowRunSummary(BaseModel):
    id: str
    analysis_type: str
    status: str
    mode: str
    model_name: str
    prompt_version: str
    snapshot_hash: str | None
    input_hash: str | None
    recommendation_count: int
    created_at: datetime


class HorizonEvidence(BaseModel):
    candidate_objective: Literal[
        "return_seeking", "risk_enforcement", "legacy"
    ]
    horizon_trading_days: int
    evaluated_recommendations: int
    average_net_value_add_pct: float
    median_net_value_add_pct: float
    positive_value_add_rate_pct: float
    average_net_active_return_pct: float
    median_net_active_return_pct: float
    positive_active_return_rate_pct: float
    expected_alpha_met_rate_pct: float | None


class ProofOfValueReport(BaseModel):
    total_runs: int
    reproducible_runs: int
    total_recommendations: int
    decision_counts: dict[str, int]
    evaluated_outcomes: int
    evaluated_recommendations: int
    horizon_evidence: list[HorizonEvidence]
    first_run_at: datetime | None
    last_run_at: datetime | None
    operational_gate: Literal["not_started", "collecting", "ready_for_review"]
    investment_evidence: Literal["insufficient", "collecting", "reviewable"]
    evidence_message: str
