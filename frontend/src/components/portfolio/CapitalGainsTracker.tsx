import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { usePrivacy } from '@/contexts/PrivacyContext';
import { api } from '@/lib/api';
import { ChevronLeft, ChevronRight, Gauge, AlertTriangle } from 'lucide-react';

function eur(value: number): string {
  return new Intl.NumberFormat('fi-FI', {
    style: 'currency',
    currency: 'EUR',
    maximumFractionDigits: 0,
  }).format(value);
}

function eur2(value: number): string {
  return new Intl.NumberFormat('fi-FI', { style: 'currency', currency: 'EUR' }).format(value);
}

export function CapitalGainsTracker() {
  const { privacyMode } = usePrivacy();
  const currentYear = new Date().getFullYear();
  const [year, setYear] = useState(currentYear);

  const { data, isLoading } = useQuery({
    queryKey: ['capital-income-summary', year],
    queryFn: () => api.getCapitalIncomeSummary(year),
  });

  if (isLoading) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium">Capital Income vs €30k Bracket</CardTitle>
        </CardHeader>
        <CardContent>
          <Skeleton className="h-[120px] w-full" />
        </CardContent>
      </Card>
    );
  }

  const threshold = data?.bracket_threshold_eur ?? 30000;
  const combined = data?.combined_taxable_eur ?? 0;
  const gains = data?.taxable_gains_eur ?? 0;
  const grossDiv = data?.gross_dividends_eur ?? 0;
  const taxableDiv = data?.taxable_dividends_eur ?? 0;
  const over = data?.amount_over_threshold_eur ?? 0;
  const remaining = data?.remaining_at_low_rate_eur ?? threshold;
  const pct = Math.min(100, Math.max(0, (combined / threshold) * 100));
  const isOver = over > 0;
  const highPct = Math.round((data?.high_rate ?? 0.34) * 100);
  const divFraction = Math.round((data?.dividend_taxable_fraction ?? 0.85) * 100);
  const hasActivity = !!data && (data.sale_count > 0 || data.dividend_payment_count > 0);
  const mask = (v: string) => (privacyMode ? '•••••' : v);

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium flex items-center gap-1.5">
            <Gauge className="h-4 w-4 text-muted-foreground" />
            Capital Income vs €30k Bracket
          </CardTitle>
          <div className="flex items-center gap-1">
            <button onClick={() => setYear((y) => y - 1)} className="p-0.5 rounded hover:bg-muted">
              <ChevronLeft className="h-4 w-4 text-muted-foreground" />
            </button>
            <span className="text-sm font-medium tabular-nums w-12 text-center">{year}</span>
            <button
              onClick={() => setYear((y) => Math.min(y + 1, currentYear))}
              disabled={year >= currentYear}
              className="p-0.5 rounded hover:bg-muted disabled:opacity-30"
            >
              <ChevronRight className="h-4 w-4 text-muted-foreground" />
            </button>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {!hasActivity ? (
          <p className="text-sm text-muted-foreground text-center py-4">
            No taxable gains or dividends in {year}
          </p>
        ) : (
          <div className="space-y-3">
            {/* Combined taxable capital income YTD */}
            <div className="flex items-baseline justify-between">
              <span className="text-2xl font-bold tabular-nums">{mask(eur2(combined))}</span>
              <span className="text-xs text-muted-foreground">of {eur(threshold)} at 30%</span>
            </div>

            {/* Progress bar */}
            <div className="h-2.5 w-full rounded-full bg-muted overflow-hidden">
              <div
                className={`h-full rounded-full transition-all ${isOver ? 'bg-amber-500' : 'bg-emerald-500'}`}
                style={{ width: `${pct}%` }}
              />
            </div>

            {/* Headroom / overflow message */}
            {isOver ? (
              <div className="flex items-start gap-1.5 text-sm text-amber-600 dark:text-amber-500">
                <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
                <span>
                  {mask(eur2(over))} over the €30k threshold — that portion is taxed at {highPct}%.
                </span>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                <span className="font-medium text-foreground">{mask(eur2(remaining))}</span> of headroom before the {highPct}% bracket.
              </p>
            )}

            {/* Breakdown: gains, taxable dividends, est. tax */}
            <div className="grid grid-cols-3 gap-2 text-sm border-t border-border pt-3">
              <div>
                <p className="text-muted-foreground text-xs">Taxable gains</p>
                <p className={`font-medium tabular-nums ${gains < 0 ? 'text-red-500' : 'text-emerald-500'}`}>
                  {mask(eur2(gains))}
                </p>
              </div>
              <div>
                <p className="text-muted-foreground text-xs">Dividends ({divFraction}%)</p>
                <p className="font-medium tabular-nums">{mask(eur2(taxableDiv))}</p>
              </div>
              <div>
                <p className="text-muted-foreground text-xs">Est. tax</p>
                <p className="font-medium tabular-nums">{mask(eur2(data.estimated_tax_eur))}</p>
              </div>
            </div>

            <p className="text-xs text-muted-foreground">
              Live from transactions: {data.sale_count} sale{data.sale_count !== 1 ? 's' : ''}
              {' '}and {data.dividend_payment_count} dividend{data.dividend_payment_count !== 1 ? 's' : ''}
              {grossDiv > 0 && (
                <> ({mask(eur2(grossDiv))} gross, {divFraction}% taxable per TVL 33a §)</>
              )}.
              {(data.excluded_ost_sale_count > 0 || data.excluded_ost_dividends_eur > 0) && (
                <> OST excluded (taxed on withdrawal): {data.excluded_ost_sale_count} sale
                {data.excluded_ost_sale_count !== 1 ? 's' : ''}, {mask(eur2(data.excluded_ost_dividends_eur))} dividends.</>
              )}
              {' '}Rental, interest and other capital income are not tracked here.
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
