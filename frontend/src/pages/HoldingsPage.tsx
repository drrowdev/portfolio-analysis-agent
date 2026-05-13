import { useHoldings } from '@/hooks/usePortfolio';
import { useAccounts } from '@/hooks/useAccounts';
import { HoldingsTable } from '@/components/portfolio/HoldingsTable';
import { QuickTradeDialog } from '@/components/portfolio/QuickTradeDialog';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Search, Loader2, Plus } from 'lucide-react';
import { useState } from 'react';

export function HoldingsPage() {
  const { data: holdings = [], isLoading } = useHoldings();
  const { data: accounts = [] } = useAccounts();
  const [search, setSearch] = useState('');
  const [accountFilter, setAccountFilter] = useState('all');
  const [tradeOpen, setTradeOpen] = useState(false);

  const accountNames: Record<string, string> = Object.fromEntries(
    accounts.map((a) => [a.id, a.name])
  );

  const cryptoAccountIds = new Set(
    accounts.filter((a) => a.account_type === 'crypto').map((a) => a.id)
  );

  const filtered = holdings.filter((h) => {
    const matchesSearch =
      !search ||
      h.symbol.toLowerCase().includes(search.toLowerCase()) ||
      h.instrument_name.toLowerCase().includes(search.toLowerCase());
    const matchesAccount = accountFilter === 'all' || h.account_id === accountFilter;
    return matchesSearch && matchesAccount;
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-8 w-8 animate-spin text-emerald-500" />
        <span className="ml-3 text-muted-foreground">Loading holdings…</span>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-foreground">Holdings</h2>
        <p className="text-sm text-muted-foreground">All your investment positions across accounts</p>
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <CardTitle className="text-sm font-medium">
              {filtered.length} positions
            </CardTitle>
            <div className="flex flex-col sm:flex-row gap-2">
              <Button size="sm" onClick={() => setTradeOpen(true)}>
                <Plus className="mr-1.5 h-4 w-4" />
                Record Trade
              </Button>
              <div className="relative">
                <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                <Input
                  placeholder="Search holdings..."
                  className="pl-8 w-full sm:w-[200px]"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </div>
              <Select value={accountFilter} onValueChange={setAccountFilter}>
                <SelectTrigger className="w-full sm:w-[180px]">
                  <SelectValue placeholder="All accounts" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All accounts</SelectItem>
                  {accounts.map((a) => (
                    <SelectItem key={a.id} value={a.id}>{a.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {filtered.length > 0 ? (
            <HoldingsTable
              holdings={filtered}
              accountNames={accountNames}
              cryptoAccountIds={cryptoAccountIds}
            />
          ) : (
            <p className="text-sm text-muted-foreground py-8 text-center">
              {holdings.length === 0 ? 'No holdings found. Upload your broker statements to get started.' : 'No holdings match your filter.'}
            </p>
          )}
        </CardContent>
      </Card>

      <QuickTradeDialog open={tradeOpen} onOpenChange={setTradeOpen} />
    </div>
  );
}
