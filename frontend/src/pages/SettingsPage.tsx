import { useAccounts } from '@/hooks/useAccounts';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Link } from '@tanstack/react-router';
import { Upload, Briefcase } from 'lucide-react';

const ACCOUNT_TYPE_LABELS: Record<string, string> = {
  arvo_osuustili: 'Arvo-osuustili (AOT)',
  osakesaastotili: 'Osakesäästötili (OST)',
  espp: 'ESPP',
};

const TAX_LABELS: Record<string, string> = {
  standard: '30/34% capital gains',
  deferred: 'Tax-deferred',
  espp: 'Qualifying disposition rules',
};

export function SettingsPage() {
  const { data: accounts = [] } = useAccounts();

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-foreground">Settings</h2>
        <p className="text-sm text-muted-foreground">Account configuration and app info</p>
      </div>

      {/* Linked Accounts */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="text-sm font-medium">Linked Broker Accounts</CardTitle>
          <Link to="/wizard">
            <Button variant="outline" size="sm">
              <Upload className="h-4 w-4 mr-2" />
              Import Data
            </Button>
          </Link>
        </CardHeader>
        <CardContent>
          {accounts.length === 0 ? (
            <p className="text-sm text-muted-foreground py-4">No accounts linked yet.</p>
          ) : (
            <div className="space-y-3">
              {accounts.map((a) => (
                <div key={a.id} className="flex items-center justify-between rounded-lg border border-border p-3">
                  <div className="flex items-center gap-3">
                    <Briefcase className="h-4 w-4 text-muted-foreground" />
                    <div>
                      <p className="text-sm font-medium text-foreground">{a.name}</p>
                      <p className="text-xs text-muted-foreground">
                        {ACCOUNT_TYPE_LABELS[a.account_type] || a.account_type} · {a.currency}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className="text-xs capitalize">{a.broker}</Badge>
                    <span className="text-xs text-muted-foreground">{TAX_LABELS[a.tax_treatment] || a.tax_treatment}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* App Info */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium">About</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm text-muted-foreground">
          <p>Portfolio Analysis Agent v0.1.0</p>
          <p>Market data: Yahoo Finance · News: NewsAPI, Finnhub · Analysis: Claude AI</p>
          <p>Scheduler: Price refresh every 15min (weekdays 07:00–21:15 UTC)</p>
        </CardContent>
      </Card>
    </div>
  );
}
