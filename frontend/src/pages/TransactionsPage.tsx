import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { toast } from '@/hooks/useToast';
import { useAccounts } from '@/hooks/useAccounts';
import type { TransactionType } from '@/types/portfolio';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { formatCurrency } from '@/lib/utils';
import { usePrivacy } from '@/contexts/PrivacyContext';
import { TaxCalculationDialog } from '@/components/portfolio/TaxCalculationDialog';
import { CapitalGainsTracker } from '@/components/portfolio/CapitalGainsTracker';
import { EnnakkoveroTracker } from '@/components/portfolio/EnnakkoveroTracker';
import {
  ArrowDownCircle,
  ArrowUpCircle,
  ChevronLeft,
  ChevronRight,
  Coins,
  FileText,
  Filter,
  Trash2,
  X,
} from 'lucide-react';

const PAGE_SIZE = 50;

// Symbols whose Finnish capital-gains tax we calculate ourselves. Other holdings
// are at Nordnet, which reports/withholds Finnish tax automatically, so the
// ennakkovero calculator is hidden for them. Mirrors the backend allowlist in
// holdings.py (`tax_filing_required`).
const TAX_FILING_SYMBOLS = new Set(['MSFT']);

const TYPE_LABELS: Record<TransactionType, string> = {
  buy: 'Buy',
  sell: 'Sell',
  dividend: 'Dividend',
  espp_purchase: 'ESPP Buy',
  espp_sale: 'ESPP Sell',
  deposit: 'Deposit',
  withdrawal: 'Withdrawal',
};

const TYPE_COLORS: Record<TransactionType, string> = {
  buy: 'text-emerald-500 bg-emerald-500/10',
  sell: 'text-red-400 bg-red-400/10',
  dividend: 'text-amber-500 bg-amber-500/10',
  espp_purchase: 'text-blue-500 bg-blue-500/10',
  espp_sale: 'text-orange-400 bg-orange-400/10',
  deposit: 'text-violet-400 bg-violet-400/10',
  withdrawal: 'text-slate-400 bg-slate-400/10',
};

function TypeBadge({ type }: { type: TransactionType }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${TYPE_COLORS[type]}`}>
      {type === 'buy' || type === 'espp_purchase' || type === 'deposit' ? (
        <ArrowDownCircle className="h-3 w-3" />
      ) : type === 'dividend' ? (
        <Coins className="h-3 w-3" />
      ) : (
        <ArrowUpCircle className="h-3 w-3" />
      )}
      {TYPE_LABELS[type]}
    </span>
  );
}

export function TransactionsPage() {
  const { mask, privacyMode } = usePrivacy();
  const { data: accounts = [] } = useAccounts();
  const [page, setPage] = useState(0);
  const [filters, setFilters] = useState<{
    account_id?: string;
    symbol?: string;
    transaction_type?: string;
    start_date?: string;
    end_date?: string;
  }>({});
  const [showFilters, setShowFilters] = useState(false);

  const accountMap: Record<string, string> = Object.fromEntries(
    accounts.map((a) => [a.id, a.name])
  );

  const queryParams = {
    ...filters,
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
  };

  const { data: transactions = [], isLoading } = useQuery({
    queryKey: ['transactions', queryParams],
    queryFn: () => api.listTransactions(queryParams),
  });

  const { data: countData } = useQuery({
    queryKey: ['transactions-count', filters],
    queryFn: () => api.countTransactions(filters),
  });

  const { data: symbols = [] } = useQuery({
    queryKey: ['transaction-symbols'],
    queryFn: () => api.listTransactionSymbols(),
  });

  // Tax calculations - fetch all to know which transactions have one
  const { data: taxCalcs = [] } = useQuery({
    queryKey: ['tax-calculations-list'],
    queryFn: () => api.listTaxCalculations(),
  });
  const taxCalcByTxId = new Map(
    taxCalcs
      .filter((tc: { transaction_id: string | null }) => tc.transaction_id)
      .map((tc: { transaction_id: string | null; id: string }) => [tc.transaction_id, tc.id])
  );
  const taxCalcMetaByTxId = new Map(
    taxCalcs
      .filter((tc) => tc.transaction_id)
      .map((tc) => [
        tc.transaction_id as string,
        {
          id: tc.id,
          declared: tc.declared,
          paid_amount_eur: tc.paid_amount_eur,
          paid_date: tc.paid_date,
        },
      ])
  );

  const queryClient = useQueryClient();

  const deleteOneCalc = useMutation({
    mutationFn: (id: string) => api.deleteTaxCalculation(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tax-calculations-list'] });
      queryClient.invalidateQueries({ queryKey: ['capital-income-summary'] });
      queryClient.invalidateQueries({ queryKey: ['declaration-summary'] });
      toast({ title: 'Tax calculation deleted' });
    },
    onError: (e: unknown) =>
      toast({
        title: 'Failed to delete tax calculation',
        description: e instanceof Error ? e.message : String(e),
        variant: 'destructive',
      }),
  });

  const deleteAllCalcs = useMutation({
    mutationFn: () => api.deleteAllTaxCalculations(),
    onSuccess: (res: { deleted: number }) => {
      queryClient.invalidateQueries({ queryKey: ['tax-calculations-list'] });
      queryClient.invalidateQueries({ queryKey: ['capital-income-summary'] });
      queryClient.invalidateQueries({ queryKey: ['declaration-summary'] });
      toast({ title: `Deleted ${res.deleted} saved tax calculation${res.deleted !== 1 ? 's' : ''}` });
    },
    onError: (e: unknown) =>
      toast({
        title: 'Failed to delete tax calculations',
        description: e instanceof Error ? e.message : String(e),
        variant: 'destructive',
      }),
  });

  function handleDeleteOneCalc(calcId: string) {
    if (window.confirm('Delete this saved tax calculation? You can re-run it afterwards.')) {
      deleteOneCalc.mutate(calcId);
    }
  }

  function handleDeleteAllCalcs() {
    if (
      window.confirm(
        `Delete all ${taxCalcs.length} saved tax calculation(s)? You can re-run them afterwards.`
      )
    ) {
      deleteAllCalcs.mutate();
    }
  }

  // State for opening tax calc from transaction row
  const [taxDialogOpen, setTaxDialogOpen] = useState(false);
  const [taxTxId, setTaxTxId] = useState<string | null>(null);
  const [taxSellParams, setTaxSellParams] = useState<{
    symbol: string;
    quantity: number;
    sell_price_eur: number;
    sell_date: string;
    fees_eur: number;
  } | null>(null);

  const totalCount = countData?.count ?? 0;
  const totalPages = Math.ceil(totalCount / PAGE_SIZE);
  const hasActiveFilters = Object.values(filters).some((v) => v);

  function clearFilters() {
    setFilters({});
    setPage(0);
  }

  function updateFilter(key: string, value: string) {
    setFilters((prev) => ({ ...prev, [key]: value || undefined }));
    setPage(0);
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-foreground">Transaction History</h2>
          <p className="text-sm text-muted-foreground">
            {totalCount.toLocaleString()} transaction{totalCount !== 1 ? 's' : ''}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {taxCalcs.length > 0 && (
            <Button
              variant="ghost"
              size="sm"
              onClick={handleDeleteAllCalcs}
              disabled={deleteAllCalcs.isPending}
              title="Delete all saved tax calculations so they can be re-run"
            >
              <Trash2 className="h-4 w-4 mr-1" />
              Delete tax calcs ({taxCalcs.length})
            </Button>
          )}
          {hasActiveFilters && (
            <Button variant="ghost" size="sm" onClick={clearFilters}>
              <X className="h-4 w-4 mr-1" />
              Clear
            </Button>
          )}
          <Button
            variant={showFilters ? 'secondary' : 'outline'}
            size="sm"
            onClick={() => setShowFilters(!showFilters)}
          >
            <Filter className="h-4 w-4 mr-1" />
            Filters
          </Button>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <CapitalGainsTracker />
        <EnnakkoveroTracker />
      </div>

      {showFilters && (
        <Card>
          <CardContent className="pt-4 pb-4">
            <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
              <div>
                <label className="text-xs text-muted-foreground mb-1 block">Account</label>
                <select
                  className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm"
                  value={filters.account_id || ''}
                  onChange={(e) => updateFilter('account_id', e.target.value)}
                >
                  <option value="">All accounts</option>
                  {accounts.map((a) => (
                    <option key={a.id} value={a.id}>{a.name}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-xs text-muted-foreground mb-1 block">Symbol</label>
                <select
                  className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm"
                  value={filters.symbol || ''}
                  onChange={(e) => updateFilter('symbol', e.target.value)}
                >
                  <option value="">All symbols</option>
                  {symbols.map((s) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-xs text-muted-foreground mb-1 block">Type</label>
                <select
                  className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm"
                  value={filters.transaction_type || ''}
                  onChange={(e) => updateFilter('transaction_type', e.target.value)}
                >
                  <option value="">All types</option>
                  {Object.entries(TYPE_LABELS).map(([val, label]) => (
                    <option key={val} value={val}>{label}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-xs text-muted-foreground mb-1 block">From</label>
                <input
                  type="date"
                  className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm"
                  value={filters.start_date || ''}
                  onChange={(e) => updateFilter('start_date', e.target.value)}
                />
              </div>
              <div>
                <label className="text-xs text-muted-foreground mb-1 block">To</label>
                <input
                  type="date"
                  className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm"
                  value={filters.end_date || ''}
                  onChange={(e) => updateFilter('end_date', e.target.value)}
                />
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-medium">Trades</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-3">
              {[...Array(8)].map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : transactions.length === 0 ? (
            <p className="text-sm text-muted-foreground py-8 text-center">
              No transactions found{hasActiveFilters ? ' matching filters' : ''}.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border">
                    <th className="py-2 px-2 text-left font-medium text-muted-foreground">Date</th>
                    <th className="py-2 px-2 text-left font-medium text-muted-foreground">Type</th>
                    <th className="py-2 px-2 text-left font-medium text-muted-foreground">Symbol</th>
                    <th className="py-2 px-2 text-left font-medium text-muted-foreground hidden sm:table-cell">Name</th>
                    <th className="py-2 px-2 text-left font-medium text-muted-foreground hidden md:table-cell">Account</th>
                    <th className="py-2 px-2 text-right font-medium text-muted-foreground">Qty</th>
                    <th className="py-2 px-2 text-right font-medium text-muted-foreground hidden sm:table-cell">Price</th>
                    <th className="py-2 px-2 text-right font-medium text-muted-foreground">Total €</th>
                    <th className="py-2 px-2 text-right font-medium text-muted-foreground hidden lg:table-cell">Fees</th>
                    <th className="py-2 px-2 text-right font-medium text-muted-foreground hidden lg:table-cell">FX</th>
                    <th className="py-2 px-1 w-8"></th>
                  </tr>
                </thead>
                <tbody>
                  {transactions.map((tx) => (
                    <tr key={tx.id} className="border-b border-border/50 hover:bg-accent/50">
                      <td className="py-2 px-2 text-muted-foreground whitespace-nowrap">
                        {new Date(tx.date).toLocaleDateString('fi-FI')}
                      </td>
                      <td className="py-2 px-2">
                        <TypeBadge type={tx.transaction_type} />
                      </td>
                      <td className="py-2 px-2 font-medium text-foreground">{tx.symbol}</td>
                      <td className="py-2 px-2 text-muted-foreground hidden sm:table-cell max-w-[200px] truncate">
                        {tx.instrument_name}
                      </td>
                      <td className="py-2 px-2 hidden md:table-cell">
                        <span className="text-xs text-muted-foreground bg-muted px-1.5 py-0.5 rounded">
                          {accountMap[tx.account_id] || '—'}
                        </span>
                      </td>
                      <td className="py-2 px-2 text-right tabular-nums">
                        {privacyMode ? mask(0) : tx.quantity.toLocaleString('fi-FI', { maximumFractionDigits: 6 })}
                      </td>
                      <td className="py-2 px-2 text-right tabular-nums hidden sm:table-cell">
                        {privacyMode ? mask(0) : formatCurrency(tx.price_eur)}
                      </td>
                      <td className={`py-2 px-2 text-right tabular-nums font-medium ${
                        tx.transaction_type === 'sell' || tx.transaction_type === 'espp_sale'
                          ? 'text-red-400'
                          : tx.transaction_type === 'dividend'
                            ? 'text-amber-500'
                            : 'text-foreground'
                      }`}>
                        {privacyMode ? mask(0) : formatCurrency(tx.total_eur)}
                      </td>
                      <td className="py-2 px-2 text-right tabular-nums text-muted-foreground hidden lg:table-cell">
                        {privacyMode ? mask(0) : tx.fees > 0 ? formatCurrency(tx.fees) : '—'}
                      </td>
                      <td className="py-2 px-2 text-right tabular-nums text-muted-foreground hidden lg:table-cell">
                        {tx.fx_rate ? tx.fx_rate.toFixed(4) : '—'}
                      </td>
                      <td className="py-2 px-1">
                        {(tx.transaction_type === 'sell' || tx.transaction_type === 'espp_sale') &&
                          TAX_FILING_SYMBOLS.has(tx.symbol) && (
                          <div className="flex items-center gap-0.5">
                            {(() => {
                              const meta = taxCalcMetaByTxId.get(tx.id);
                              const saved = !!meta;
                              const declared = !!meta?.declared;
                              const color = declared
                                ? 'text-emerald-400'
                                : saved
                                  ? 'text-amber-400'
                                  : 'text-muted-foreground/40 hover:text-muted-foreground';
                              const title = declared
                                ? 'Tax declared & paid — view calculation'
                                : saved
                                  ? 'Saved but not yet declared/paid — view calculation'
                                  : 'Calculate tax';
                              return (
                            <button
                              className={`p-1 rounded hover:bg-accent ${color}`}
                              title={title}
                              onClick={() => {
                                setTaxTxId(tx.id);
                                setTaxSellParams({
                                  symbol: tx.symbol,
                                  quantity: Number(tx.quantity),
                                  sell_price_eur: Number(tx.price_eur),
                                  sell_date: tx.date,
                                  fees_eur: Number(tx.fees),
                                });
                                setTaxDialogOpen(true);
                              }}
                            >
                              <FileText className="h-4 w-4" />
                            </button>
                              );
                            })()}
                            {taxCalcByTxId.has(tx.id) && (
                              <button
                                className="p-1 rounded text-muted-foreground/40 hover:text-red-400 hover:bg-accent"
                                title="Delete saved tax calculation"
                                disabled={deleteOneCalc.isPending}
                                onClick={() => handleDeleteOneCalc(taxCalcByTxId.get(tx.id) as string)}
                              >
                                <Trash2 className="h-4 w-4" />
                              </button>
                            )}
                          </div>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {totalPages > 1 && (
            <div className="flex items-center justify-between pt-4 border-t border-border mt-4">
              <p className="text-xs text-muted-foreground">
                Showing {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, totalCount)} of {totalCount}
              </p>
              <div className="flex items-center gap-1">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                  disabled={page === 0}
                >
                  <ChevronLeft className="h-4 w-4" />
                </Button>
                <span className="text-sm text-muted-foreground px-2">
                  {page + 1} / {totalPages}
                </span>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                  disabled={page >= totalPages - 1}
                >
                  <ChevronRight className="h-4 w-4" />
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <TaxCalculationDialog
        open={taxDialogOpen}
        onOpenChange={setTaxDialogOpen}
        sellParams={taxSellParams}
        existingCalc={taxTxId ? taxCalcMetaByTxId.get(taxTxId) ?? null : null}
      />
    </div>
  );
}
