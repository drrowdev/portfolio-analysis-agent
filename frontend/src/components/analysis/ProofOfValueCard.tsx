import { AlertTriangle, BarChart3, CheckCircle2, Loader2, RefreshCw, ShieldCheck } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import {
  useBacktestRuns,
  useBacktestSpecification,
  usePersonalLedgerCoverage,
  useProofOfValuePolicy,
  useProofOfValueReport,
  useProofOfValueSnapshot,
  useShadowRuns,
  useTriggerBacktest,
  useUpdateProofOfValuePolicy,
} from '@/hooks/useAnalysis';
import type { BacktestTrack, ProofOfValuePolicy } from '@/hooks/useAnalysis';
import { toast } from '@/hooks/useToast';

type NumericPolicyField = Exclude<
  keyof ProofOfValuePolicy,
  'mode' | 'benchmark_name' | 'benchmark_ticker' | 'benchmark_currency'
>;

const POLICY_FIELDS: {
  key: NumericPolicyField;
  label: string;
  suffix: string;
  required: boolean;
}[] = [
  { key: 'investment_horizon_years', label: 'Investment horizon', suffix: 'years', required: true },
  { key: 'max_drawdown_pct', label: 'Maximum drawdown', suffix: '%', required: true },
  { key: 'max_annualized_volatility_pct', label: 'Maximum annual volatility', suffix: '%', required: true },
  { key: 'max_tracking_error_pct', label: 'Maximum tracking error', suffix: '%', required: true },
  { key: 'max_single_position_pct', label: 'Maximum single position', suffix: '%', required: true },
  { key: 'max_sector_pct', label: 'Maximum sector exposure', suffix: '%', required: true },
  { key: 'max_annual_turnover_pct', label: 'Maximum annual turnover', suffix: '%', required: true },
  { key: 'estimated_transaction_cost_bps', label: 'Estimated one-way trade cost', suffix: 'bps', required: true },
  { key: 'minimum_expected_net_alpha_pct', label: 'Minimum expected net alpha', suffix: '%', required: true },
  { key: 'price_stale_after_hours', label: 'Price freshness limit', suffix: 'hours', required: false },
];

function formatMetric(value: number | null | undefined, suffix = '%') {
  return value == null ? 'Not available' : `${value.toFixed(1)}${suffix}`;
}

export function ProofOfValueCard() {
  const policyQuery = useProofOfValuePolicy();
  const snapshotQuery = useProofOfValueSnapshot();
  const runsQuery = useShadowRuns();
  const reportQuery = useProofOfValueReport();
  const backtestSpecQuery = useBacktestSpecification();
  const ledgerCoverageQuery = usePersonalLedgerCoverage();
  const backtestRunsQuery = useBacktestRuns();
  const triggerBacktest = useTriggerBacktest();
  const updatePolicy = useUpdateProofOfValuePolicy();

  const policy = policyQuery.data;
  const snapshot = snapshotQuery.data;
  const performance = snapshot?.metrics.performance;
  const concentration = snapshot?.metrics.concentration;
  const latestBacktest = triggerBacktest.data;
  const latestHoldout = latestBacktest?.split_results?.find(
    (split) => split.period === 'holdout',
  ) ?? latestBacktest?.scenarios?.standard?.splits.find(
    (split) => split.period === 'holdout',
  ) ?? latestBacktest?.scenarios?.deferred?.splits.find(
    (split) => split.period === 'holdout',
  );

  function savePolicy(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!policy) return;
    const form = new FormData(event.currentTarget);
    const numberValue = (key: NumericPolicyField) => {
      const value = String(form.get(key) ?? '').trim();
      return value === '' ? null : Number(value);
    };
    const payload: ProofOfValuePolicy = {
      mode: 'shadow',
      benchmark_name: 'S&P 500 Total Return',
      benchmark_ticker: '^SP500TR',
      benchmark_currency: 'EUR',
      investment_horizon_years: numberValue('investment_horizon_years'),
      max_drawdown_pct: numberValue('max_drawdown_pct'),
      max_annualized_volatility_pct: numberValue('max_annualized_volatility_pct'),
      max_tracking_error_pct: numberValue('max_tracking_error_pct'),
      max_single_position_pct: numberValue('max_single_position_pct'),
      max_sector_pct: numberValue('max_sector_pct'),
      max_annual_turnover_pct: numberValue('max_annual_turnover_pct'),
      estimated_transaction_cost_bps: numberValue('estimated_transaction_cost_bps'),
      minimum_expected_net_alpha_pct: numberValue('minimum_expected_net_alpha_pct'),
      price_stale_after_hours: numberValue('price_stale_after_hours') ?? 96,
    };
    updatePolicy.mutate(payload, {
      onSuccess: () => toast({ title: 'Proof-of-value policy saved' }),
      onError: (error) =>
        toast({
          title: 'Failed to save policy',
          description: error.message,
          variant: 'destructive',
        }),
    });
  }

  function runBacktest(track: BacktestTrack) {
    triggerBacktest.mutate(track, {
      onSuccess: (result) => {
        const blocker = result.blockers?.[0];
        toast({
          title: result.status === 'blocked' ? 'Backtest blocked' : 'Backtest completed',
          description: blocker ?? `${result.track.replaceAll('_', ' ')} evidence was saved immutably.`,
          variant: result.status === 'blocked' ? 'destructive' : 'default',
        });
      },
      onError: (error) =>
        toast({
          title: 'Backtest failed',
          description: error.message,
          variant: 'destructive',
        }),
    });
  }

  if (policyQuery.isLoading) {
    return (
      <Card>
        <CardContent className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading proof-of-value policy…
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="border-emerald-500/30">
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-emerald-500" />
            <CardTitle className="text-base">Proof of Value</CardTitle>
            <Badge variant="secondary">Shadow mode</Badge>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => snapshotQuery.refetch()}
            disabled={snapshotQuery.isFetching}
          >
            {snapshotQuery.isFetching ? (
              <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="mr-1.5 h-4 w-4" />
            )}
            Refresh scorecard
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">
          No trade is actionable until its data, risk budget, costs, and benchmark comparison are complete.
        </p>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Metric label="1Y active return" value={formatMetric(performance?.active_return_pct)} />
          <Metric label="Annual volatility" value={formatMetric(performance?.annualized_volatility_pct)} />
          <Metric label="Maximum drawdown" value={formatMetric(performance?.max_drawdown_pct)} />
          <Metric
            label="Largest position"
            value={
              concentration?.largest_position_symbol
                ? `${concentration.largest_position_symbol} ${formatMetric(concentration.largest_position_pct)}`
                : 'Not available'
            }
          />
          <Metric
          label="Gross YTD turnover"
          value={formatMetric(snapshot?.metrics.turnover?.ytd_turnover_pct)}
          />
        </div>

        <div className="rounded-md border border-border p-3">
          <div className="mb-2 flex items-center gap-2">
            {snapshot?.data_quality.can_recommend_trades ? (
              <CheckCircle2 className="h-4 w-4 text-emerald-500" />
            ) : (
              <AlertTriangle className="h-4 w-4 text-amber-500" />
            )}
            <span className="text-sm font-medium">
              {snapshot?.data_quality.can_recommend_trades
                ? 'Data is eligible for shadow recommendations'
                : 'Trade recommendations are blocked'}
            </span>
          </div>
          {snapshotQuery.error && (
            <p className="text-xs text-destructive">{snapshotQuery.error.message}</p>
          )}
          {(snapshot?.data_quality.issues.length ?? 0) > 0 && (
            <ul className="space-y-1">
              {snapshot!.data_quality.issues.map((issue) => (
                <li key={`${issue.code}-${issue.symbols.join(',')}`} className="text-xs text-muted-foreground">
                  <span className={issue.severity === 'blocking' ? 'text-amber-500' : ''}>
                    {issue.severity.toUpperCase()}:
                  </span>{' '}
                  {issue.message}
                  {issue.symbols.length > 0 && ` (${issue.symbols.join(', ')})`}
                </li>
              ))}
            </ul>
          )}
        </div>

        {snapshot?.baselines && (
          <div className="rounded-md border border-border p-3">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium">Rules-only comparator</span>
              <Badge
                variant={
                  snapshot.baselines.deterministic_policy_status === 'within_limits'
                    ? 'success'
                    : 'warning'
                }
              >
                {snapshot.baselines.deterministic_policy_status.replace('_', ' ')}
              </Badge>
            </div>
            <div className="grid gap-2 sm:grid-cols-3">
              <Metric
                label="Hold current · 1Y"
                value={formatMetric(snapshot.baselines.hold_current_return_pct)}
              />
              <Metric
                label="Benchmark · 1Y"
                value={formatMetric(snapshot.baselines.benchmark_return_pct)}
              />
              <Metric
                label="Historical active return"
                value={formatMetric(snapshot.baselines.historical_active_return_pct)}
              />
            </div>
            <ul className="mt-3 space-y-1">
              {snapshot.baselines.signals
                .filter((signal) => signal.status !== 'pass')
                .map((signal) => (
                  <li key={signal.code} className="text-xs text-muted-foreground">
                    <span className={signal.status === 'breach' ? 'text-amber-500' : ''}>
                      {signal.status.toUpperCase()}:
                    </span>{' '}
                    {signal.message}
                  </li>
                ))}
            </ul>
          </div>
        )}

        <div className="rounded-md border border-border p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <BarChart3 className="h-4 w-4 text-emerald-500" />
              <span className="text-sm font-medium">Pre-registered alpha backtests</span>
              {backtestSpecQuery.data && (
                <Badge variant="secondary">
                  {backtestSpecQuery.data.specification.spec_version}
                </Badge>
              )}
            </div>
            <span className="font-mono text-[10px] text-muted-foreground">
              {backtestSpecQuery.data?.specification_hash.slice(0, 12)}
            </span>
          </div>
          <p className="mt-2 text-xs text-muted-foreground">
            One locked price-only hypothesis, no parameter search. The personal track tests
            applicability on FIFO-reconstructed holdings; the universe track tests selection
            alpha against point-in-time members. Historical results are evidence, not proof.
          </p>
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            <div className="rounded border border-border p-2 text-xs">
              <p className="font-medium">Actual portfolio cohorts</p>
              <p className="mt-1 text-muted-foreground">
                {ledgerCoverageQuery.data
                  ? `${ledgerCoverageQuery.data.accounts.filter((account) => account.eligible).length}/${ledgerCoverageQuery.data.accounts.length} accounts reconcile`
                  : 'Checking transaction reconciliation…'}
              </p>
              {(ledgerCoverageQuery.data?.blockers.length ?? 0) > 0 && (
                <p className="mt-1 text-amber-500">
                  {ledgerCoverageQuery.data!.blockers[0]}
                </p>
              )}
              <Button
                className="mt-2"
                size="sm"
                variant="outline"
                disabled={!policy?.is_complete || triggerBacktest.isPending}
                onClick={() => runBacktest('actual_portfolio')}
              >
                {triggerBacktest.isPending && triggerBacktest.variables === 'actual_portfolio' && (
                  <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                )}
                Run personal track
              </Button>
            </div>
            <div className="rounded border border-border p-2 text-xs">
              <p className="font-medium">Point-in-time S&amp;P 500 universe</p>
              <p className="mt-1 text-muted-foreground">
                {backtestSpecQuery.data
                  ? `${backtestSpecQuery.data.membership_interval_count} hashed membership intervals`
                  : 'Loading universe provenance…'}
              </p>
              <p className="mt-1 text-muted-foreground">
                Requires configured licensed EUR prices including removed and delisted names.
              </p>
              <Button
                className="mt-2"
                size="sm"
                variant="outline"
                disabled={!policy?.is_complete || triggerBacktest.isPending}
                onClick={() => runBacktest('sp500_universe')}
              >
                {triggerBacktest.isPending && triggerBacktest.variables === 'sp500_universe' && (
                  <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                )}
                Run universe track
              </Button>
            </div>
          </div>
          {latestBacktest && (
            <div className="mt-3 rounded border border-border p-2 text-xs">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant={latestBacktest.status === 'blocked' ? 'warning' : 'secondary'}>
                  {latestBacktest.status.replaceAll('_', ' ')}
                </Badge>
                <span>{latestBacktest.track.replaceAll('_', ' ')}</span>
                {latestBacktest.promotion_eligible && <Badge variant="success">gate passed</Badge>}
              </div>
              {latestHoldout && (
                <p className="mt-1 text-muted-foreground">
                  Holdout:{' '}
                  {latestHoldout.net_active_cagr_pct != null
                    ? `${formatMetric(latestHoldout.net_active_cagr_pct)} net active CAGR`
                    : `${formatMetric(latestHoldout.overlay_net_value_add_pct)} cohort value-add`}
                </p>
              )}
              {(latestBacktest.blockers ?? latestBacktest.promotion_blockers)?.[0] && (
                <p className="mt-1 text-amber-500">
                  {(latestBacktest.blockers ?? latestBacktest.promotion_blockers)![0]}
                </p>
              )}
            </div>
          )}
          {(backtestRunsQuery.data?.length ?? 0) > 0 && (
            <div className="mt-3 space-y-1">
              {backtestRunsQuery.data!.map((run) => (
                <div key={run.id} className="flex flex-wrap justify-between gap-2 text-xs">
                  <span>
                    {run.track.replaceAll('_', ' ')} · {run.status.replaceAll('_', ' ')}
                  </span>
                  <span className="text-muted-foreground">
                    {new Date(run.created_at).toLocaleString('fi-FI')} · {run.input_hash.slice(0, 10)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        {(runsQuery.data?.length ?? 0) > 0 && (
          <div className="rounded-md border border-border p-3">
            <p className="mb-2 text-sm font-medium">Recent immutable shadow runs</p>
            <div className="space-y-2">
              {runsQuery.data!.map((run) => (
                <div
                  key={run.id}
                  className="flex flex-wrap items-center justify-between gap-2 text-xs"
                >
                  <div className="flex items-center gap-2">
                    <Badge variant="secondary">{run.analysis_type.replace('_', ' ')}</Badge>
                    <span className="text-muted-foreground">
                      {new Date(run.created_at).toLocaleString('fi-FI')}
                    </span>
                  </div>
                  <span className="text-muted-foreground">
                    {run.recommendation_count} decision
                    {run.recommendation_count === 1 ? '' : 's'} · {run.prompt_version}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {reportQuery.data && (
          <div className="rounded-md border border-border p-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium">Evidence status</span>
              <Badge variant="secondary">
                {reportQuery.data.operational_gate.replaceAll('_', ' ')}
              </Badge>
              <Badge
                variant={
                  reportQuery.data.investment_evidence === 'reviewable'
                    ? 'success'
                    : 'warning'
                }
              >
                alpha evidence: {reportQuery.data.investment_evidence}
              </Badge>
            </div>
            <p className="mt-2 text-xs text-muted-foreground">
              {reportQuery.data.evidence_message}
            </p>
            <p className="mt-2 text-xs text-muted-foreground">
              {reportQuery.data.reproducible_runs}/{reportQuery.data.total_runs} reproducible runs ·{' '}
              {reportQuery.data.evaluated_recommendations} evaluated recommendations ·{' '}
              {reportQuery.data.evaluated_outcomes} horizon marks
            </p>
            {reportQuery.data.horizon_evidence.length > 0 && (
              <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                {reportQuery.data.horizon_evidence.map((horizon) => (
                  <div
                    key={`${horizon.candidate_objective}-${horizon.horizon_trading_days}`}
                    className="rounded border border-border p-2 text-xs"
                  >
                    <p className="font-medium">
                      {horizon.candidate_objective.replaceAll('_', ' ')} ·{' '}
                      {horizon.horizon_trading_days}-session
                    </p>
                    <p className="mt-1 text-muted-foreground">
                      {horizon.candidate_objective === 'return_seeking'
                        ? 'Net alpha'
                        : 'Net active return (not alpha)'}
                      : {formatMetric(horizon.average_net_active_return_pct)}
                    </p>
                    <p className="text-muted-foreground">
                      Value-add: {formatMetric(horizon.average_net_value_add_pct)} · n=
                      {horizon.evaluated_recommendations}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {policy && (
          <details className="rounded-md border border-border p-3">
            <summary className="cursor-pointer text-sm font-medium">
              Configure benchmark and risk contract
              {!policy.is_complete && (
                <Badge variant="warning" className="ml-2 text-[10px]">
                  {policy.missing_fields.length} required
                </Badge>
              )}
            </summary>
            <p className="mt-2 text-xs text-muted-foreground">
              Benchmark: {policy.benchmark_name} ({policy.benchmark_ticker}) in {policy.benchmark_currency}.
              It remains provisional until configurable benchmark pricing is implemented.
            </p>
            <form
              key={POLICY_FIELDS.map(({ key }) => `${key}:${policy[key] ?? ''}`).join('|')}
              onSubmit={savePolicy}
            >
              <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {POLICY_FIELDS.map((field) => (
                  <label key={field.key} className="space-y-1">
                    <span className="text-xs font-medium">
                      {field.label}
                      {field.required && <span className="text-amber-500"> *</span>}
                    </span>
                    <div className="flex items-center gap-2">
                      <Input
                        name={field.key}
                        type="number"
                        min="0"
                        step="0.1"
                        defaultValue={policy[field.key] ?? ''}
                      />
                      <span className="w-12 text-xs text-muted-foreground">{field.suffix}</span>
                    </div>
                  </label>
                ))}
              </div>
              <div className="mt-4 flex justify-end">
                <Button type="submit" disabled={updatePolicy.isPending}>
                  {updatePolicy.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  Save policy
                </Button>
              </div>
            </form>
          </details>
        )}
      </CardContent>
    </Card>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-sm font-semibold">{value}</p>
    </div>
  );
}
