import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';

export interface AnalysisSource {
  name: string;
  url: string;
  date: string;
}

export interface AnalysisInsight {
  title: string;
  detail: string;
  severity: 'info' | 'warning' | 'action';
  sources?: AnalysisSource[];
}

export interface AnalysisRecommendation {
  action: string;
  rationale: string;
  account_type: string;
  priority: 'high' | 'medium' | 'low';
  decision?: 'buy' | 'sell' | 'hold' | 'rebalance' | 'monitor' | 'abstain';
  confidence?: 'high' | 'medium' | 'low';
  urgency?: 'immediate' | 'soon' | 'routine' | 'none';
  candidate_id?: string | null;
  candidate_group_id?: string | null;
  candidate_objective?: 'return_seeking' | 'risk_enforcement' | null;
  symbol?: string | null;
  quantity?: number | null;
  amount_eur?: number | null;
  timeframe?: string | null;
  valid_until?: string | null;
  expected_net_alpha_pct?: number | null;
  expected_alpha_horizon_days?: 1 | 5 | 20 | 60 | null;
  downside_pct?: number | null;
  estimated_transaction_cost_eur?: number | null;
  estimated_tax_impact_eur?: number | null;
  risk_impact?: string | null;
  reference_price_eur?: number | null;
  currency?: string | null;
  execution_assumption?: 'cash' | 'benchmark' | null;
}

export interface AnalysisContent {
  summary: string;
  insights: AnalysisInsight[];
  recommendations: AnalysisRecommendation[];
  risk_factors: string[];
  meta?: {
    mode: 'shadow';
    as_of: string;
    snapshot_hash: string | null;
    input_hash?: string | null;
    model: string;
    prompt_version: string;
    can_recommend_trades: boolean;
    data_quality_issues: string[];
  };
}

export interface ProofOfValuePolicy {
  mode: 'shadow';
  benchmark_name: 'S&P 500 Total Return';
  benchmark_ticker: '^SP500TR';
  benchmark_currency: 'EUR';
  investment_horizon_years: number | null;
  max_drawdown_pct: number | null;
  max_annualized_volatility_pct: number | null;
  max_tracking_error_pct: number | null;
  max_single_position_pct: number | null;
  max_sector_pct: number | null;
  max_annual_turnover_pct: number | null;
  estimated_transaction_cost_bps: number | null;
  minimum_expected_net_alpha_pct: number | null;
  price_stale_after_hours: number;
}

export interface ProofOfValuePolicyState extends ProofOfValuePolicy {
  is_complete: boolean;
  missing_fields: string[];
  objective: string;
  return_methodology: string;
}

export interface DataQualityIssue {
  code: string;
  severity: 'info' | 'warning' | 'blocking';
  message: string;
  symbols: string[];
}

export interface ProofOfValueSnapshot {
  schema_version: string;
  as_of: string;
  snapshot_hash: string;
  policy: ProofOfValuePolicyState;
  data_quality: {
    can_recommend_trades: boolean;
    issues: DataQualityIssue[];
  };
  cash_eur: number;
  invested_value_eur: number;
  total_portfolio_value_eur: number;
  metrics: {
    performance: {
      period: string;
      observations: number;
      portfolio_return_pct: number | null;
      benchmark_return_pct: number | null;
      active_return_pct: number | null;
      annualized_volatility_pct: number | null;
      benchmark_annualized_volatility_pct: number | null;
      tracking_error_pct: number | null;
      beta: number | null;
      max_drawdown_pct: number | null;
      benchmark_max_drawdown_pct: number | null;
    } | null;
    concentration: {
      invested_value_eur: number;
      position_count: number;
      largest_position_symbol: string | null;
      largest_position_pct: number | null;
      top_five_positions_pct: number | null;
      herfindahl_index: number | null;
    };
    sectors: {
      sector: string;
      value_eur: number;
      weight_pct: number;
    }[];
    turnover?: {
      year: number;
      traded_notional_eur: number;
      portfolio_value_eur: number;
      ytd_turnover_pct: number | null;
      methodology: string;
    } | null;
  };
  baselines: {
    hold_current_return_pct: number | null;
    benchmark_return_pct: number | null;
    historical_active_return_pct: number | null;
    deterministic_policy_status: 'within_limits' | 'review_required' | 'blocked';
    signals: {
      code: string;
      status: 'pass' | 'breach' | 'unavailable';
      metric_value: number | null;
      policy_limit: number | null;
      message: string;
    }[];
    methodology: string;
  };
}

export interface GuidanceBrief {
  schema_version: string;
  as_of: string;
  snapshot_hash: string;
  health: {
    status: 'on_track' | 'review' | 'blocked';
    title: string;
    detail: string;
    origin: 'rule';
  };
  best_action: {
    status: 'no_action' | 'review' | 'blocked';
    decision: 'hold' | 'abstain';
    title: string;
    detail: string;
    origin: 'rule' | 'quant_model';
    provenance: string;
    as_of: string;
  };
  current_exceptions: Array<{
    code: string;
    severity: 'info' | 'warning' | 'blocking';
    title: string;
    detail: string;
    origin: 'rule';
  }>;
  tax_and_cost: {
    year: number;
    tracked_taxable_income_eur: number;
    estimated_tax_eur: number;
    remaining_at_low_rate_eur: number;
    amount_over_threshold_eur: number;
    ytd_turnover_pct: number | null;
    transaction_cost_assumption_bps: number | null;
    quantified_savings_eur: number | null;
    detail: string;
  };
  passive_baseline: {
    period: string;
    index_name: string;
    index_ticker: string;
    currency: string;
    status: 'available' | 'unavailable';
    portfolio_return_pct: number | null;
    index_return_pct: number | null;
    active_return_pct: number | null;
    comparison_basis: string;
    excluded_from_comparison: string[];
    investable_comparator_status: 'available' | 'not_configured';
    investable_comparator_name: string | null;
    investable_comparator_ticker: string | null;
    investable_comparator_return_pct: number | null;
    investable_comparator_message: string;
  };
  snapshot: ProofOfValueSnapshot;
  disclaimer: string;
}

export interface GuidanceRefreshResponse {
  guidance: GuidanceBrief;
  steps: Array<{
    key: 'market_prices' | 'guidance';
    status: 'completed' | 'blocked';
    detail: string;
    updated_count: number | null;
  }>;
}

export interface ShadowRunSummary {
  id: string;
  analysis_type: string;
  status: string;
  mode: string;
  model_name: string;
  prompt_version: string;
  snapshot_hash: string | null;
  input_hash: string | null;
  recommendation_count: number;
  created_at: string;
}

export interface ProofOfValueReport {
  total_runs: number;
  reproducible_runs: number;
  total_recommendations: number;
  decision_counts: Record<string, number>;
  evaluated_outcomes: number;
  evaluated_recommendations: number;
  horizon_evidence: Array<{
    candidate_objective: 'return_seeking' | 'risk_enforcement' | 'legacy';
    horizon_trading_days: number;
    evaluated_recommendations: number;
    average_net_value_add_pct: number;
    median_net_value_add_pct: number;
    positive_value_add_rate_pct: number;
    average_net_active_return_pct: number;
    median_net_active_return_pct: number;
    positive_active_return_rate_pct: number;
    expected_alpha_met_rate_pct: number | null;
  }>;
  first_run_at: string | null;
  last_run_at: string | null;
  operational_gate: 'not_started' | 'collecting' | 'ready_for_review';
  investment_evidence: 'insufficient' | 'collecting' | 'reviewable';
  evidence_message: string;
}

export type BacktestTrack = 'actual_portfolio' | 'sp500_universe';

export interface BacktestSplitResult {
  period: string;
  observations?: number;
  months?: number;
  cohort_count?: number;
  net_active_cagr_pct?: number | null;
  overlay_net_value_add_pct?: number | null;
  active_return_ci_lower_pct?: number | null;
  active_return_ci_upper_pct?: number | null;
}

export interface BacktestResult {
  run_id: string;
  input_hash: string;
  status: string;
  track: BacktestTrack;
  spec_version: string;
  specification_hash: string;
  blockers?: string[];
  promotion_eligible?: boolean;
  promotion_blockers?: string[];
  split_results?: BacktestSplitResult[];
  scenarios?: Record<string, {
    status?: string;
    splits: BacktestSplitResult[];
    blockers?: string[];
  }>;
}

export interface BacktestRunSummary {
  id: string;
  track: BacktestTrack;
  status: string;
  spec_version: string;
  specification_hash: string;
  input_hash: string;
  promotion_eligible: boolean;
  created_at: string;
}

export interface BacktestSpecification {
  specification: {
    spec_version: string;
    status: 'locked';
    hypothesis: string;
    anti_overfitting: {
      parameter_search_allowed: boolean;
      historical_evidence_is_proof_of_future_alpha: boolean;
    };
  };
  specification_hash: string;
  membership_provenance: {
    source_commit: string;
    coverage_start: string;
    default_backtest_start: string;
    known_limitations: string[];
  };
  membership_hash: string;
  membership_interval_count: number;
}

export interface PersonalLedgerCoverage {
  can_backtest_all_accounts: boolean;
  accounts: Array<{
    account_id: string;
    account_name: string;
    eligible: boolean;
    blockers: string[];
  }>;
  blockers: string[];
  methodology: string;
}

export type AnalysisType = 'daily_summary' | 'rebalance' | 'tax_optimization' | 'news_impact';

export interface AnalysisHistoryItem {
  id: string;
  analysis_type: AnalysisType;
  content: AnalysisContent;
  created_at: string;
}

const ENDPOINT_MAP: Record<string, string> = {
  'daily-summary': '/analysis/daily-summary',
  'rebalance': '/analysis/rebalance',
  'tax-optimization': '/analysis/tax-optimization',
  'news-impact': '/analysis/news-impact',
};

export function useAnalysisHistory(limit = 20) {
  return useQuery<AnalysisHistoryItem[]>({
    queryKey: ['analysis', 'history', limit],
    queryFn: () => api.get(`/analysis/history?limit=${limit}`),
    staleTime: 60_000,
  });
}

export function useTriggerAnalysis() {
  const queryClient = useQueryClient();
  return useMutation<AnalysisContent, Error, string>({
    mutationFn: (analysisType) => {
      const endpoint = ENDPOINT_MAP[analysisType];
      if (!endpoint) throw new Error(`Unknown analysis type: ${analysisType}`);
      return api.post(endpoint, {});
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['analysis', 'history'] });
      queryClient.invalidateQueries({ queryKey: ['analysis', 'shadow-runs'] });
      queryClient.invalidateQueries({ queryKey: ['analysis', 'proof-of-value-report'] });
    },
  });
}

export function useProofOfValuePolicy() {
  return useQuery<ProofOfValuePolicyState>({
    queryKey: ['analysis', 'policy'],
    queryFn: () => api.get('/analysis/policy'),
    staleTime: 60_000,
  });
}

export function useUpdateProofOfValuePolicy() {
  const queryClient = useQueryClient();
  return useMutation<ProofOfValuePolicyState, Error, ProofOfValuePolicy>({
    mutationFn: (policy) => api.put('/analysis/policy', policy),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['analysis', 'policy'] });
      queryClient.invalidateQueries({ queryKey: ['analysis', 'proof-of-value'] });
      queryClient.invalidateQueries({ queryKey: ['analysis', 'guidance'] });
    },
  });
}

export function useProofOfValueSnapshot() {
  return useQuery<ProofOfValueSnapshot>({
    queryKey: ['analysis', 'proof-of-value'],
    queryFn: () => api.get('/analysis/proof-of-value'),
    staleTime: 5 * 60_000,
    retry: false,
  });
}

export function useGuidance() {
  return useQuery<GuidanceBrief>({
    queryKey: ['analysis', 'guidance'],
    queryFn: () => api.get('/analysis/guidance'),
    staleTime: 5 * 60_000,
    retry: false,
  });
}

export function useRefreshGuidance() {
  const queryClient = useQueryClient();
  return useMutation<GuidanceRefreshResponse, Error>({
    mutationFn: () => api.post('/analysis/guidance/refresh', {}),
    onSuccess: (result) => {
      queryClient.setQueryData(['analysis', 'guidance'], result.guidance);
      queryClient.invalidateQueries({ queryKey: ['analysis', 'proof-of-value'] });
      queryClient.invalidateQueries({ queryKey: ['portfolio'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
    },
  });
}

export function useShadowRuns(limit = 5) {
  return useQuery<ShadowRunSummary[]>({
    queryKey: ['analysis', 'shadow-runs', limit],
    queryFn: () => api.get(`/analysis/shadow-runs?limit=${limit}`),
    staleTime: 60_000,
  });
}

export function useProofOfValueReport() {
  return useQuery<ProofOfValueReport>({
    queryKey: ['analysis', 'proof-of-value-report'],
    queryFn: () => api.get('/analysis/proof-of-value-report'),
    staleTime: 60_000,
  });
}

export function useBacktestSpecification() {
  return useQuery<BacktestSpecification>({
    queryKey: ['analysis', 'backtests', 'specification'],
    queryFn: () => api.get('/analysis/backtests/specification'),
    staleTime: Infinity,
  });
}

export function usePersonalLedgerCoverage() {
  return useQuery<PersonalLedgerCoverage>({
    queryKey: ['analysis', 'backtests', 'ledger-coverage'],
    queryFn: () => api.get('/analysis/backtests/ledger-coverage'),
    staleTime: 60_000,
  });
}

export function useBacktestRuns(limit = 5) {
  return useQuery<BacktestRunSummary[]>({
    queryKey: ['analysis', 'backtests', 'runs', limit],
    queryFn: () => api.get(`/analysis/backtests?limit=${limit}`),
    staleTime: 60_000,
  });
}

export function useTriggerBacktest() {
  const queryClient = useQueryClient();
  return useMutation<BacktestResult, Error, BacktestTrack>({
    mutationFn: (track) => api.post(`/analysis/backtests/${track}`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['analysis', 'backtests', 'runs'] });
      queryClient.invalidateQueries({
        queryKey: ['analysis', 'backtests', 'ledger-coverage'],
      });
    },
  });
}
