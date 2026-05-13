import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { usePrivacy } from '@/contexts/PrivacyContext';
import { api } from '@/lib/api';
import { TrendingUp, TrendingDown, ChevronLeft, ChevronRight } from 'lucide-react';

interface RealizedTrade {
  date: string;
  symbol: string;
  quantity: number;
  proceeds_eur: number;
  cost_basis_eur: number;
  fees_eur: number;
  realized_gain_eur: number;
}

interface RealizedGainsData {
  year: number;
  total_realized_eur: number;
  total_gains_eur: number;
  total_losses_eur: number;
  trade_count: number;
  trades: RealizedTrade[];
}

function formatCurrency(value: number): string {
  return new Intl.NumberFormat('fi-FI', { style: 'currency', currency: 'EUR' }).format(value);
}

export function RealizedGainsCard() {
  const { privacyMode } = usePrivacy();
  const currentYear = new Date().getFullYear();
  const [year, setYear] = useState(currentYear);

  const { data, isLoading } = useQuery({
    queryKey: ['realized-gains', year],
    queryFn: () => api.get<RealizedGainsData>(`/transactions/realized-gains?year=${year}`),
    staleTime: 30 * 60 * 1000, // 30 min — only changes on new transactions
  });

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium">Realized Gains</CardTitle>
        </CardHeader>
        <CardContent>
          <Skeleton className="h-[120px] w-full" />
        </CardContent>
      </Card>
    );
  }

  const noData = !data || data.trade_count === 0;
  const isPositive = (data?.total_realized_eur ?? 0) >= 0;

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium">Realized Gains</CardTitle>
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
        {noData ? (
          <p className="text-sm text-muted-foreground text-center py-4">No closed trades in {year}</p>
        ) : (
          <div className="space-y-3">
            {/* Total P&L */}
            <div className="flex items-center gap-2">
              {isPositive ? (
                <TrendingUp className="h-5 w-5 text-emerald-500" />
              ) : (
                <TrendingDown className="h-5 w-5 text-red-500" />
              )}
              <span className={`text-xl font-bold tabular-nums ${isPositive ? 'text-emerald-500' : 'text-red-500'}`}>
                {privacyMode ? '•••••' : formatCurrency(data!.total_realized_eur)}
              </span>
            </div>

            {/* Gains / Losses breakdown */}
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div>
                <p className="text-muted-foreground">Gains</p>
                <p className="font-medium text-emerald-500 tabular-nums">
                  {privacyMode ? '•••' : formatCurrency(data!.total_gains_eur)}
                </p>
              </div>
              <div>
                <p className="text-muted-foreground">Losses</p>
                <p className="font-medium text-red-500 tabular-nums">
                  {privacyMode ? '•••' : formatCurrency(data!.total_losses_eur)}
                </p>
              </div>
            </div>

            {/* Trade count */}
            <p className="text-xs text-muted-foreground">
              {data!.trade_count} closed trade{data!.trade_count !== 1 ? 's' : ''}
            </p>

            {/* Recent trades */}
            {data!.trades.length > 0 && (
              <div className="border-t border-border pt-3 mt-3 space-y-2">
                <p className="text-xs font-medium text-muted-foreground">Recent Trades</p>
                {data!.trades.slice(0, 5).map((t, i) => (
                  <div key={i} className="flex items-center justify-between text-sm">
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{t.symbol}</span>
                      <span className="text-xs text-muted-foreground">{t.date.split('-').reverse().join('.')}</span>
                    </div>
                    <span className={`tabular-nums font-medium ${t.realized_gain_eur >= 0 ? 'text-emerald-500' : 'text-red-500'}`}>
                      {privacyMode ? '•••' : formatCurrency(t.realized_gain_eur)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
