import { useQuery } from '@tanstack/react-query';
import { Link, useParams } from '@tanstack/react-router';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { usePrivacy } from '@/contexts/PrivacyContext';
import { api } from '@/lib/api';
import { formatCurrency, formatPercent, formatNumber } from '@/lib/utils';
import { ArrowLeft, TrendingUp, TrendingDown } from 'lucide-react';
import type { Holding, Transaction } from '@/types/portfolio';

export function PositionDetailPage() {
  const { symbol } = useParams({ strict: false }) as { symbol: string };
  const { privacyMode } = usePrivacy();

  const mask = () => '•••••';

  // Get all holdings to find the specific one
  const { data: holdings, isLoading: holdingsLoading } = useQuery({
    queryKey: ['holdings'],
    queryFn: () => api.get<Holding[]>('/holdings/'),
  });

  // Get transactions for this symbol
  const { data: transactions, isLoading: txLoading } = useQuery({
    queryKey: ['transactions', symbol],
    queryFn: () => api.get<Transaction[]>(`/transactions/?symbol=${symbol}&limit=50`),
    enabled: !!symbol,
  });

  const holding = holdings?.find((h) => h.symbol === symbol);

  if (holdingsLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-[300px] w-full" />
      </div>
    );
  }

  if (!holding) {
    return (
      <div className="space-y-4">
        <Link to="/" className="text-sm text-muted-foreground hover:text-foreground flex items-center gap-1">
          <ArrowLeft className="h-4 w-4" /> Back to Dashboard
        </Link>
        <p className="text-muted-foreground">Position not found: {symbol}</p>
      </div>
    );
  }

  const isPositive = (holding.unrealized_pnl_eur ?? 0) >= 0;
  const dayChange = holding.price_change_pct ?? 0;
  const dayPositive = dayChange >= 0;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <Link to="/" className="text-sm text-muted-foreground hover:text-foreground flex items-center gap-1 mb-2">
            <ArrowLeft className="h-4 w-4" /> Back
          </Link>
          <h1 className="text-2xl font-bold">{holding.symbol}</h1>
          <p className="text-muted-foreground">{holding.instrument_name}</p>
        </div>
        <div className="text-right">
          <p className="text-2xl font-bold tabular-nums">
            {privacyMode ? mask() : holding.current_price_eur != null ? formatCurrency(holding.current_price_eur) : '—'}
          </p>
          <p className={`text-sm font-medium ${dayPositive ? 'text-emerald-500' : 'text-red-500'}`}>
            {privacyMode ? mask() : `${dayPositive ? '+' : ''}${dayChange.toFixed(2)}% today`}
          </p>
        </div>
      </div>

      {/* Key metrics */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card>
          <CardContent className="pt-4 pb-4">
            <p className="text-xs text-muted-foreground">Market Value</p>
            <p className="text-lg font-bold tabular-nums">
              {privacyMode ? mask() : formatCurrency(holding.current_value_eur ?? 0)}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 pb-4">
            <p className="text-xs text-muted-foreground">Total Cost</p>
            <p className="text-lg font-bold tabular-nums">
              {privacyMode ? mask() : formatCurrency(holding.total_cost_eur)}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 pb-4">
            <p className="text-xs text-muted-foreground">Unrealized P&L</p>
            <div className="flex items-center gap-1">
              {isPositive ? <TrendingUp className="h-4 w-4 text-emerald-500" /> : <TrendingDown className="h-4 w-4 text-red-500" />}
              <p className={`text-lg font-bold tabular-nums ${isPositive ? 'text-emerald-500' : 'text-red-500'}`}>
                {privacyMode ? mask() : formatCurrency(holding.unrealized_pnl_eur ?? 0)}
              </p>
            </div>
            <p className={`text-xs ${isPositive ? 'text-emerald-500' : 'text-red-500'}`}>
              {privacyMode ? mask() : formatPercent(holding.unrealized_pnl_pct ?? 0)}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 pb-4">
            <p className="text-xs text-muted-foreground">Portfolio Weight</p>
            <p className="text-lg font-bold tabular-nums">
              {privacyMode ? mask() : `${Number(holding.portfolio_weight_pct ?? 0).toFixed(1)}%`}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Position details */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium">Position Details</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex justify-between text-sm">
              <span className="text-muted-foreground">Quantity</span>
              <span className="font-mono">{privacyMode ? mask() : formatNumber(holding.total_quantity, 4)}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-muted-foreground">Avg Cost / Share</span>
              <span className="font-mono">{privacyMode ? mask() : formatCurrency(holding.avg_cost_basis_eur)}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-muted-foreground">Current Price</span>
              <span className="font-mono">{privacyMode ? mask() : formatCurrency(holding.current_price_eur ?? 0)}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-muted-foreground">Currency</span>
              <span>{holding.currency}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-muted-foreground">ISIN</span>
              <span className="font-mono text-xs">{holding.isin || '—'}</span>
            </div>
          </CardContent>
        </Card>

        {/* Transaction history for this position */}
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium">Recent Transactions</CardTitle>
          </CardHeader>
          <CardContent>
            {txLoading ? (
              <Skeleton className="h-[150px] w-full" />
            ) : !transactions || transactions.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-4">No transactions found</p>
            ) : (
              <div className="space-y-2 max-h-[300px] overflow-y-auto">
                {transactions.slice(0, 20).map((t) => (
                  <div key={t.id} className="flex items-center justify-between text-sm py-1 border-b border-border last:border-0">
                    <div className="flex items-center gap-2">
                      <Badge
                        variant="outline"
                        className={`text-[10px] ${
                          t.transaction_type === 'buy' || t.transaction_type === 'espp_purchase'
                            ? 'border-emerald-500 text-emerald-500'
                            : t.transaction_type === 'sell' || t.transaction_type === 'espp_sale'
                            ? 'border-red-500 text-red-500'
                            : t.transaction_type === 'dividend'
                            ? 'border-amber-500 text-amber-500'
                            : ''
                        }`}
                      >
                        {t.transaction_type}
                      </Badge>
                      <span className="text-xs text-muted-foreground">{t.date.split('-').reverse().join('.')}</span>
                    </div>
                    <div className="text-right">
                      <span className="font-mono text-xs">
                        {privacyMode ? mask() : formatCurrency(t.total_eur)}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
