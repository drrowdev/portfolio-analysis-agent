import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { usePrivacy } from '@/contexts/PrivacyContext';
import { api } from '@/lib/api';
import { toast } from '@/hooks/useToast';
import {
  ChevronLeft,
  ChevronRight,
  Receipt,
  CheckCircle2,
  Circle,
  AlertTriangle,
} from 'lucide-react';

function eur2(value: number): string {
  return new Intl.NumberFormat('fi-FI', { style: 'currency', currency: 'EUR' }).format(value);
}

function fiDate(iso: string | null): string {
  if (!iso) return '';
  return iso.slice(0, 10).split('-').reverse().join('.');
}

export function EnnakkoveroTracker() {
  const { privacyMode } = usePrivacy();
  const currentYear = new Date().getFullYear();
  const [year, setYear] = useState(currentYear);
  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ['declaration-summary', year],
    queryFn: () => api.getDeclarationSummary(year),
  });

  const toggle = useMutation({
    mutationFn: ({
      id,
      declared,
      paid_amount_eur,
    }: {
      id: string;
      declared: boolean;
      paid_amount_eur: string;
    }) =>
      api.setTaxCalculationDeclaration(id, {
        declared,
        paid_amount_eur: declared ? paid_amount_eur : null,
        paid_date: declared ? new Date().toISOString().slice(0, 10) : null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['declaration-summary'] });
      queryClient.invalidateQueries({ queryKey: ['tax-calculations-list'] });
    },
    onError: (err) =>
      toast({ title: 'Error', description: (err as Error).message, variant: 'destructive' }),
  });

  const mask = (v: string) => (privacyMode ? '•••••' : v);

  if (isLoading) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium">Ennakkovero — declared vs remaining (MSFT)</CardTitle>
        </CardHeader>
        <CardContent>
          <Skeleton className="h-[120px] w-full" />
        </CardContent>
      </Card>
    );
  }

  const total = Number(data?.total_tax_eur ?? 0);
  const declared = Number(data?.declared_tax_eur ?? 0);
  const remaining = Number(data?.remaining_tax_eur ?? 0);
  const overUnder = Number(data?.over_under_eur ?? 0);
  const paidCount = data?.paid_count ?? 0;
  const sales = data?.sales ?? [];
  const hasSales = sales.length > 0;
  const declaredPct = total > 0 ? Math.min(100, (declared / total) * 100) : 0;

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium flex items-center gap-1.5">
            <Receipt className="h-4 w-4 text-muted-foreground" />
            Ennakkovero — declared vs remaining (MSFT)
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
        {!hasSales ? (
          <p className="text-sm text-muted-foreground text-center py-4">
            No saved MSFT tax calculations for {year}. Open a MSFT sale and save its calculation to
            track its ennakkovero here.
          </p>
        ) : (
          <div className="space-y-3">
            {/* Headline: remaining to declare */}
            <div className="flex items-baseline justify-between">
              <div>
                <span className="text-2xl font-bold tabular-nums">{mask(eur2(remaining))}</span>
                <span className="text-xs text-muted-foreground ml-2">still to declare</span>
              </div>
              <span className="text-xs text-muted-foreground">
                {mask(eur2(declared))} of {mask(eur2(total))} done
              </span>
            </div>

            {/* Progress: declared / total */}
            <div className="h-2.5 w-full rounded-full bg-muted overflow-hidden">
              <div
                className={`h-full rounded-full transition-all ${
                  remaining <= 0 ? 'bg-emerald-500' : 'bg-sky-500'
                }`}
                style={{ width: `${declaredPct}%` }}
              />
            </div>

            {remaining <= 0 ? (
              <p className="text-sm text-emerald-600 dark:text-emerald-500 flex items-center gap-1.5">
                <CheckCircle2 className="h-4 w-4 shrink-0" />
                All {year} MSFT sales declared.
              </p>
            ) : (
              <p className="text-sm text-muted-foreground">
                <span className="font-medium text-foreground">{mask(eur2(remaining))}</span> of
                advance tax still to declare/pay in OmaVero.
              </p>
            )}

            {/* Reconciliation: paid vs corrected computed figure */}
            {paidCount > 0 && Math.abs(overUnder) >= 0.01 && (
              <div
                className={`flex items-start gap-1.5 text-xs rounded-md p-2 ${
                  overUnder > 0
                    ? 'text-amber-600 dark:text-amber-500 bg-amber-500/10'
                    : 'text-red-600 dark:text-red-500 bg-red-500/10'
                }`}
              >
                <AlertTriangle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
                <span>
                  For declared sales you paid {mask(eur2(Math.abs(overUnder)))}{' '}
                  {overUnder > 0 ? 'more' : 'less'} than the corrected figure. The year-end
                  assessment reconciles {overUnder > 0 ? 'the overpayment (refunded)' : 'the shortfall (residual tax)'}.
                </span>
              </div>
            )}

            {/* Per-sale list with quick declared toggle */}
            <div className="border-t border-border pt-2 space-y-1">
              {sales.map((s) => (
                <button
                  key={s.id}
                  onClick={() =>
                    toggle.mutate({ id: s.id, declared: !s.declared, paid_amount_eur: s.computed_tax_eur })
                  }
                  disabled={toggle.isPending}
                  className="w-full flex items-center justify-between gap-2 text-xs py-1.5 px-1 rounded hover:bg-muted/50 disabled:opacity-50"
                  title={s.declared ? 'Mark as not yet declared' : 'Mark as declared & paid'}
                >
                  <span className="flex items-center gap-2">
                    {s.declared ? (
                      <CheckCircle2 className="h-4 w-4 text-emerald-500 shrink-0" />
                    ) : (
                      <Circle className="h-4 w-4 text-muted-foreground/40 shrink-0" />
                    )}
                    <span className="text-muted-foreground">{fiDate(s.sell_date)}</span>
                    <span className="tabular-nums">{Number(s.quantity_sold)} kpl</span>
                  </span>
                  <span className="flex items-center gap-2">
                    {s.declared && s.paid_amount_eur && (
                      <span className="text-muted-foreground">
                        paid {mask(eur2(Number(s.paid_amount_eur)))}
                        {s.paid_date ? ` · ${fiDate(s.paid_date)}` : ''}
                      </span>
                    )}
                    <span className={`font-mono ${s.declared ? 'text-muted-foreground line-through' : 'font-semibold'}`}>
                      {mask(eur2(Number(s.computed_tax_eur)))}
                    </span>
                  </span>
                </button>
              ))}
            </div>

            <p className="text-xs text-muted-foreground">
              Per-sale figures are marginal and stack chronologically, so they sum to the year's
              total advance tax. Click a sale to toggle declared (defaults to the computed amount and
              today's date — edit the exact amount in the sale's tax dialog).
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
