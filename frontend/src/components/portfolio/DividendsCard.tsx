import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { usePrivacy } from '@/contexts/PrivacyContext';
import { api } from '@/lib/api';
import { Banknote, ChevronLeft, ChevronRight } from 'lucide-react';

interface DividendBySymbol {
  symbol: string;
  instrument_name: string;
  total_eur: number;
  payments: number;
  last_payment: string;
}

interface DividendsData {
  year: number;
  total_dividends_eur: number;
  payment_count: number;
  by_symbol: DividendBySymbol[];
}

function formatCurrency(value: number): string {
  return new Intl.NumberFormat('fi-FI', { style: 'currency', currency: 'EUR' }).format(value);
}

export function DividendsCard() {
  const { privacyMode } = usePrivacy();
  const currentYear = new Date().getFullYear();
  const [year, setYear] = useState(currentYear);

  const { data, isLoading } = useQuery({
    queryKey: ['dividends', year],
    queryFn: () => api.get<DividendsData>(`/transactions/dividends?year=${year}`),
    staleTime: 30 * 60 * 1000, // 30 min — only changes when new dividends detected
  });

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium">Dividends ({year})</CardTitle>
        </CardHeader>
        <CardContent>
          <Skeleton className="h-[100px] w-full" />
        </CardContent>
      </Card>
    );
  }

  const noData = !data || data.payment_count === 0;

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium">Dividends</CardTitle>
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
          <p className="text-sm text-muted-foreground text-center py-4">No dividends received in {year}</p>
        ) : (
          <div className="space-y-3">
            {/* Total */}
            <div className="flex items-center gap-2">
              <Banknote className="h-5 w-5 text-emerald-500" />
              <span className="text-xl font-bold tabular-nums text-emerald-500">
                {privacyMode ? '•••••' : formatCurrency(data!.total_dividends_eur)}
              </span>
            </div>

            <p className="text-xs text-muted-foreground">
              {data!.payment_count} payment{data!.payment_count !== 1 ? 's' : ''} received
            </p>

            {/* By symbol */}
            {data!.by_symbol.length > 0 && (
              <div className="border-t border-border pt-3 space-y-2">
                {data!.by_symbol.map((s) => (
                  <div key={s.symbol} className="flex items-center justify-between text-sm">
                    <div>
                      <span className="font-medium">{s.symbol}</span>
                      <span className="text-xs text-muted-foreground ml-2">×{s.payments}</span>
                    </div>
                    <span className="tabular-nums font-medium text-foreground">
                      {privacyMode ? '•••' : formatCurrency(s.total_eur)}
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
