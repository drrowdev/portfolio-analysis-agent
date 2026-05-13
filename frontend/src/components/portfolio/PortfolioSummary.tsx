import type { PortfolioSummary as PortfolioSummaryType } from '@/types/portfolio';
import { Card, CardContent } from '@/components/ui/card';
import { TrendingUp, TrendingDown, Wallet, PiggyBank } from 'lucide-react';
import { formatCurrency, formatPercent } from '@/lib/utils';
import { usePrivacy } from '@/contexts/PrivacyContext';

interface PortfolioSummaryProps {
  summary: PortfolioSummaryType;
}

export function PortfolioSummary({ summary }: PortfolioSummaryProps) {
  const { mask, privacyMode } = usePrivacy();
  const isPositive = summary.total_unrealized_pnl_eur >= 0;
  const isDailyPositive = (summary.daily_pnl_eur ?? 0) >= 0;

  const cards = [
    {
      label: 'Total Value',
      value: privacyMode ? mask(0) : formatCurrency(summary.total_value_eur),
      icon: Wallet,
      color: 'text-emerald-500',
      bgColor: 'bg-emerald-500/10',
    },
    {
      label: 'Total Cost',
      value: privacyMode ? mask(0) : formatCurrency(summary.total_cost_eur),
      icon: PiggyBank,
      color: 'text-blue-500',
      bgColor: 'bg-blue-500/10',
    },
    {
      label: 'Total P/L',
      value: privacyMode ? mask(0) : formatCurrency(summary.total_unrealized_pnl_eur),
      subValue: privacyMode
        ? mask(0)
        : summary.total_unrealized_pnl_pct != null
          ? formatPercent(summary.total_unrealized_pnl_pct)
          : undefined,
      icon: isPositive ? TrendingUp : TrendingDown,
      color: isPositive ? 'text-emerald-500' : 'text-red-500',
      bgColor: isPositive ? 'bg-emerald-500/10' : 'bg-red-500/10',
    },
    {
      label: "Today's P/L",
      value: privacyMode
        ? mask(0)
        : summary.daily_pnl_eur != null
          ? formatCurrency(summary.daily_pnl_eur)
          : '—',
      subValue: privacyMode
        ? mask(0)
        : summary.daily_pnl_pct != null
          ? formatPercent(summary.daily_pnl_pct)
          : undefined,
      icon: isDailyPositive ? TrendingUp : TrendingDown,
      color: isDailyPositive ? 'text-emerald-500' : 'text-red-500',
      bgColor: isDailyPositive ? 'bg-emerald-500/10' : 'bg-red-500/10',
    },
  ];

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 sm:gap-4">
      {cards.map((card) => (
        <Card key={card.label}>
          <CardContent className="p-3 sm:p-6">
            <div className="flex items-center justify-between gap-2">
              <div className="space-y-1 min-w-0">
                <p className="text-xs sm:text-sm text-muted-foreground">{card.label}</p>
                <p className={`text-lg sm:text-2xl font-bold ${card.color}`}>{card.value}</p>
                {card.subValue && (
                  <p className={`text-xs sm:text-sm ${card.color}`}>{card.subValue}</p>
                )}
              </div>
              <div className={`hidden sm:block rounded-full p-3 ${card.bgColor}`}>
                <card.icon className={`h-5 w-5 ${card.color}`} />
              </div>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
