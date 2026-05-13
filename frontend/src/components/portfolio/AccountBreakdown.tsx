import type { AccountSummary } from '@/types/portfolio';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { formatCurrency, formatPercent } from '@/lib/utils';
import { usePrivacy } from '@/contexts/PrivacyContext';

interface AccountBreakdownProps {
  accounts: AccountSummary[];
}

export function AccountBreakdown({ accounts }: AccountBreakdownProps) {
  const { mask, privacyMode } = usePrivacy();

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-medium">Account Breakdown</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          {accounts.map((a) => {
            const isPositive = a.unrealized_pnl_eur >= 0;
            return (
              <div key={a.account_id} className="flex items-center justify-between rounded-lg border border-border p-4">
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-foreground">{a.account_name}</span>
                    <Badge variant="secondary" className="text-xs capitalize">
                      {a.broker}
                    </Badge>
                  </div>
                </div>
                <div className="text-right space-y-1">
                  <p className="font-mono font-medium text-foreground">
                    {privacyMode ? mask(0) : formatCurrency(a.total_value_eur)}
                  </p>
                  <p className={`text-sm font-mono ${privacyMode ? '' : isPositive ? 'text-emerald-500' : 'text-red-500'}`}>
                    {privacyMode
                      ? mask(0)
                      : `${formatCurrency(a.unrealized_pnl_eur)} (${a.unrealized_pnl_pct != null ? formatPercent(a.unrealized_pnl_pct) : '—'})`}
                  </p>
                </div>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}
