import {
  AlertTriangle,
  CheckCircle2,
  CircleDollarSign,
  Clock3,
  Landmark,
  ReceiptText,
  ShieldCheck,
  Target,
  TrendingDown,
  TrendingUp,
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { GuidanceBrief } from '@/hooks/useAnalysis';
import { cn } from '@/lib/utils';

interface ConsumerGuidanceProps {
  guidance?: GuidanceBrief;
  loading: boolean;
  error?: Error | null;
}

function formatPercent(value: number | null | undefined) {
  return value == null ? 'Not available' : `${value.toFixed(1)}%`;
}

function formatEuro(value: number | null | undefined) {
  if (value == null) return 'Not available';
  return new Intl.NumberFormat('fi-FI', {
    style: 'currency',
    currency: 'EUR',
    maximumFractionDigits: 0,
  }).format(value);
}

function formatTimestamp(value: string) {
  return new Date(value).toLocaleString('fi-FI', {
    day: 'numeric',
    month: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function ConsumerGuidance({
  guidance,
  loading,
  error,
}: ConsumerGuidanceProps) {
  if (loading) {
    return (
      <Card>
        <CardContent className="flex items-center gap-3 p-6 text-sm text-muted-foreground">
          <Clock3 className="h-4 w-4 animate-pulse" />
          Loading portfolio data...
        </CardContent>
      </Card>
    );
  }

  if (error || !guidance) {
    return (
      <Card className="border-amber-500/40">
        <CardContent className="flex items-start gap-3 p-6">
          <AlertTriangle className="mt-0.5 h-5 w-5 text-amber-500" />
          <div>
            <p className="font-medium text-foreground">Portfolio cockpit unavailable</p>
            <p className="mt-1 text-sm text-muted-foreground">
              {error?.message ?? 'No portfolio guidance was returned.'}
            </p>
          </div>
        </CardContent>
      </Card>
    );
  }

  const snapshot = guidance.snapshot;
  const concentration = snapshot.metrics.concentration;
  const healthTone = guidance.health.status === 'on_track' ? 'success' : 'warning';
  const HealthIcon = guidance.health.status === 'on_track'
    ? CheckCircle2
    : AlertTriangle;
  const activeReturn = guidance.passive_baseline.active_return_pct;
  const ActiveReturnIcon = activeReturn != null && activeReturn < 0
    ? TrendingDown
    : TrendingUp;
  const bandValue = guidance.tax_and_cost.amount_over_threshold_eur > 0
    ? formatEuro(guidance.tax_and_cost.amount_over_threshold_eur)
    : formatEuro(guidance.tax_and_cost.remaining_at_low_rate_eur);
  const bandDetail = guidance.tax_and_cost.amount_over_threshold_eur > 0
    ? 'above the 30% band'
    : 'remaining in the 30% band';

  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-5">
        <Card className="lg:col-span-3">
          <CardHeader className="pb-3">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Portfolio health
                </p>
                <CardTitle className="mt-1 flex items-center gap-2 text-xl">
                  <HealthIcon
                    className={cn(
                      'h-5 w-5',
                      healthTone === 'success' ? 'text-emerald-500' : 'text-amber-500',
                    )}
                  />
                  {guidance.health.title}
                </CardTitle>
              </div>
              <Badge variant={healthTone}>
                {guidance.health.status === 'on_track' ? 'Within limits' : 'Review'}
              </Badge>
            </div>
            <p className="max-w-3xl text-sm text-muted-foreground">
              {guidance.health.detail}
            </p>
          </CardHeader>
          <CardContent>
            <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
              <FactMetric
                icon={TrendingUp}
                label="Portfolio return"
                value={formatPercent(guidance.passive_baseline.portfolio_return_pct)}
                detail={guidance.passive_baseline.period}
              />
              <FactMetric
                icon={Target}
                label="Versus index"
                value={formatPercent(activeReturn)}
                detail="before fees and tax"
              />
              <FactMetric
                icon={ShieldCheck}
                label="Largest position"
                value={
                  concentration.largest_position_symbol
                    ? `${concentration.largest_position_symbol} ${formatPercent(concentration.largest_position_pct)}`
                    : 'Not available'
                }
                detail={
                  snapshot.policy.max_single_position_pct == null
                    ? 'limit not set'
                    : `${snapshot.policy.max_single_position_pct.toFixed(1)}% limit`
                }
              />
              <FactMetric
                icon={ReceiptText}
                label="YTD turnover"
                value={formatPercent(guidance.tax_and_cost.ytd_turnover_pct)}
                detail="gross traded notional"
              />
            </div>
            <p className="mt-3 text-[11px] text-muted-foreground">
              Updated {formatTimestamp(guidance.as_of)}
            </p>
          </CardContent>
        </Card>

        <Card className="border-emerald-500/25 lg:col-span-2">
          <CardHeader className="pb-3">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Current stance
            </p>
            <CardTitle className="text-lg">{guidance.best_action.title}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-sm text-muted-foreground">{guidance.best_action.detail}</p>
            <p className="text-[11px] text-muted-foreground">{guidance.disclaimer}</p>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="pb-3">
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Performance benchmark
              </p>
              <CardTitle className="mt-1 text-lg">
                {guidance.passive_baseline.index_name}
              </CardTitle>
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid gap-2 sm:grid-cols-3">
              <FactMetric
                icon={TrendingUp}
                label="Portfolio"
                value={formatPercent(guidance.passive_baseline.portfolio_return_pct)}
                detail={guidance.passive_baseline.currency}
              />
              <FactMetric
                icon={Target}
                label="Index"
                value={formatPercent(guidance.passive_baseline.index_return_pct)}
                detail={guidance.passive_baseline.index_ticker}
              />
              <FactMetric
                icon={ActiveReturnIcon}
                label="Difference"
                value={formatPercent(activeReturn)}
                detail="before fees and tax"
              />
            </div>
            <p className="text-xs text-muted-foreground">
              {guidance.passive_baseline.comparison_basis} Excludes{' '}
              {guidance.passive_baseline.excluded_from_comparison.join(', ')}.
            </p>
            <div className="rounded-md border border-dashed border-amber-500/40 bg-amber-500/5 p-3">
              <div className="flex items-center gap-2">
                <AlertTriangle className="h-4 w-4 text-amber-500" />
                <p className="text-xs font-medium text-foreground">
                  Investable ETF baseline not configured
                </p>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                {guidance.passive_baseline.investable_comparator_message}
              </p>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Tax and cost facts
              </p>
              <CardTitle className="mt-1 text-lg">
                Tracked {guidance.tax_and_cost.year}
              </CardTitle>
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid gap-2 sm:grid-cols-3">
              <FactMetric
                icon={Landmark}
                label="Taxable income"
                value={formatEuro(guidance.tax_and_cost.tracked_taxable_income_eur)}
                detail="recorded transactions"
              />
              <FactMetric
                icon={CircleDollarSign}
                label="Estimated tax"
                value={formatEuro(guidance.tax_and_cost.estimated_tax_eur)}
                detail="tracked income only"
              />
              <FactMetric
                icon={ReceiptText}
                label="Tax band"
                value={bandValue}
                detail={bandDetail}
              />
            </div>
            <p className="text-xs text-muted-foreground">{guidance.tax_and_cost.detail}</p>
            <p className="text-[11px] text-muted-foreground">
              Transaction-cost assumption:{' '}
              {guidance.tax_and_cost.transaction_cost_assumption_bps == null
                ? 'not configured'
                : `${guidance.tax_and_cost.transaction_cost_assumption_bps.toFixed(0)} bps`}
            </p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Current exceptions
              </p>
              <CardTitle className="mt-1 text-lg">Items needing attention</CardTitle>
            </div>
            <Badge variant="outline">
              {guidance.current_exceptions.length} exception
              {guidance.current_exceptions.length === 1 ? '' : 's'}
            </Badge>
          </div>
        </CardHeader>
        <CardContent>
          {guidance.current_exceptions.length === 0 ? (
            <div className="rounded-md border border-dashed border-border p-4 text-sm text-muted-foreground">
              Nothing currently requires attention.
            </div>
          ) : (
            <div className="grid gap-3 md:grid-cols-2">
              {guidance.current_exceptions.map((exception, index) => (
                <div
                  key={`${exception.code}-${index}`}
                  className={cn(
                    'rounded-md border border-border border-l-4 p-3',
                    exception.severity === 'blocking' && 'border-l-red-500',
                    exception.severity === 'warning' && 'border-l-amber-500',
                    exception.severity === 'info' && 'border-l-blue-500',
                  )}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-sm font-medium text-foreground">{exception.title}</p>
                  </div>
                  <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                    {exception.detail}
                  </p>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function FactMetric({
  icon: Icon,
  label,
  value,
  detail,
}: {
  icon: typeof TrendingUp;
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="rounded-md border border-border p-3">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Icon className="h-3.5 w-3.5" />
        {label}
      </div>
      <p className="mt-1 text-base font-semibold text-foreground">{value}</p>
      <p className="mt-0.5 text-[11px] text-muted-foreground">{detail}</p>
    </div>
  );
}
