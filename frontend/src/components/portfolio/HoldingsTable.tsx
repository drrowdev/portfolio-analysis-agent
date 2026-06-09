import type { Holding } from '@/types/portfolio';
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { formatCurrency, formatPercent, formatNumber } from '@/lib/utils';
import { usePrivacy } from '@/contexts/PrivacyContext';
import { Moon, Sunrise, Bitcoin } from 'lucide-react';
import { useNavigate } from '@tanstack/react-router';

function ExtendedHoursTag({ state, changePct, privacyMode, mask }: {
  state: string | null;
  changePct: number | null;
  privacyMode: boolean;
  mask: (v: string | number | undefined | null) => string;
}) {
  if (!state || !['PRE', 'POST', 'POSTPOST', 'PREPRE', 'CLOSED'].includes(state) || changePct == null) {
    return null;
  }

  const isPre = state === 'PRE';
  const label = isPre ? 'Pre-market' : 'After-hours';
  const Icon = isPre ? Sunrise : Moon;
  const color = changePct >= 0 ? 'text-emerald-500' : 'text-red-500';

  return (
    <span
      className="inline-flex items-center gap-1 text-xs leading-tight"
      title={label}
    >
      <Icon className="h-3.5 w-3.5 text-blue-400" />
      <span className={color}>
        {privacyMode ? mask(0) : `${changePct >= 0 ? '+' : ''}${changePct.toFixed(2)}%`}
      </span>
    </span>
  );
}

function HoldingsRows({ holdings, accountNames, privacyMode, mask, isCrypto }: {
  holdings: Holding[];
  accountNames: Record<string, string>;
  privacyMode: boolean;
  mask: (v: string | number | undefined | null) => string;
  isCrypto?: boolean;
}) {
  const navigate = useNavigate();
  return (
    <>
      {holdings.map((h) => (
        <TableRow key={h.id} className="cursor-pointer hover:bg-muted/50" onClick={() => navigate({ to: '/position/$symbol', params: { symbol: h.symbol } })}>
          <TableCell className="font-mono font-medium">{h.symbol}</TableCell>
          <TableCell className="max-w-[200px] truncate hidden sm:table-cell">{h.instrument_name}</TableCell>
          {!isCrypto && (
            <TableCell className="hidden sm:table-cell">
              <Badge variant="outline" className="text-xs">
                {accountNames[h.account_id] || h.account_id}
              </Badge>
            </TableCell>
          )}
          <TableCell className="text-right font-mono">
            {privacyMode ? mask(0) : formatNumber(h.total_quantity, Number(h.total_quantity) % 1 === 0 ? 0 : isCrypto ? 6 : 3)}
          </TableCell>
          <TableCell className="text-right font-mono hidden sm:table-cell">
            {privacyMode
              ? mask(0)
              : h.avg_cost_basis_native != null
                ? formatCurrency(h.avg_cost_basis_native, h.currency || 'EUR')
                : formatCurrency(h.avg_cost_basis_eur)}
          </TableCell>
          <TableCell className="text-right font-mono">
            {privacyMode
              ? mask(0)
              : h.current_price_native != null
                ? formatCurrency(h.current_price_native, h.currency || 'EUR')
                : h.current_price_eur != null
                  ? formatCurrency(h.current_price_eur)
                  : '—'}
          </TableCell>
          <TableCell className="text-right font-mono">
            <div className="flex flex-col items-end gap-0.5 leading-tight">
              {privacyMode ? (
                <span className="text-muted-foreground">{mask(0)}</span>
              ) : h.price_change_pct != null ? (
                <span
                  className={`inline-block rounded px-1.5 py-0.5 text-xs font-medium ${
                    h.price_change_pct >= 0
                      ? 'bg-emerald-500/15 text-emerald-400'
                      : 'bg-red-500/15 text-red-400'
                  }`}
                >
                  {h.price_change_pct >= 0 ? '+' : ''}{h.price_change_pct.toFixed(2)}%
                </span>
              ) : (
                <span className="text-muted-foreground">—</span>
              )}
              <ExtendedHoursTag state={h.market_state} changePct={h.extended_hours_change_pct} privacyMode={privacyMode} mask={mask} />
            </div>
          </TableCell>
          <TableCell className="text-right font-mono font-medium">
            {privacyMode ? mask(0) : h.current_value_eur != null ? formatCurrency(h.current_value_eur) : '—'}
          </TableCell>
          <TableCell className={`text-right font-mono hidden sm:table-cell ${privacyMode ? '' : (h.unrealized_pnl_eur ?? 0) >= 0 ? 'text-emerald-500' : 'text-red-500'}`}>
            {privacyMode ? mask(0) : h.unrealized_pnl_eur != null ? formatCurrency(h.unrealized_pnl_eur) : '—'}
          </TableCell>
          <TableCell className={`text-right font-mono ${privacyMode ? '' : (h.unrealized_pnl_pct ?? 0) >= 0 ? 'text-emerald-500' : 'text-red-500'}`}>
            {privacyMode ? mask(0) : h.unrealized_pnl_pct != null ? formatPercent(h.unrealized_pnl_pct) : '—'}
          </TableCell>
          <TableCell className="text-right font-mono hidden sm:table-cell">
            {privacyMode ? mask(0) : h.portfolio_weight_pct != null ? `${Number(h.portfolio_weight_pct).toFixed(1)}%` : '—'}
          </TableCell>
        </TableRow>
      ))}
    </>
  );
}

interface HoldingsTableProps {
  holdings: Holding[];
  accountNames?: Record<string, string>;
  cryptoAccountIds?: Set<string>;
}

export function HoldingsTable({ holdings, accountNames = {}, cryptoAccountIds = new Set() }: HoldingsTableProps) {
  const { mask, privacyMode } = usePrivacy();

  const stockHoldings = holdings
    .filter((h) => !cryptoAccountIds.has(h.account_id))
    .sort((a, b) => (b.portfolio_weight_pct ?? 0) - (a.portfolio_weight_pct ?? 0));

  const cryptoHoldings = holdings
    .filter((h) => cryptoAccountIds.has(h.account_id))
    .sort((a, b) => (b.current_value_eur ?? 0) - (a.current_value_eur ?? 0));

  const tableHeader = (isCrypto?: boolean) => (
    <TableHeader>
      <TableRow>
        <TableHead>Symbol</TableHead>
        <TableHead className="hidden sm:table-cell">Name</TableHead>
        {!isCrypto && <TableHead className="hidden sm:table-cell">Account</TableHead>}
        <TableHead className="text-right">Qty</TableHead>
        <TableHead className="text-right hidden sm:table-cell">Avg Cost</TableHead>
        <TableHead className="text-right">Price</TableHead>
        <TableHead className="text-right">Today</TableHead>
        <TableHead className="text-right">Value</TableHead>
        <TableHead className="text-right hidden sm:table-cell">P/L €</TableHead>
        <TableHead className="text-right">P/L %</TableHead>
        <TableHead className="text-right hidden sm:table-cell">Weight</TableHead>
      </TableRow>
    </TableHeader>
  );

  return (
    <div className="space-y-6">
      {stockHoldings.length > 0 && (
        <div className="overflow-x-auto -mx-2 sm:mx-0">
          <Table>
            {tableHeader()}
            <TableBody>
              <HoldingsRows holdings={stockHoldings} accountNames={accountNames} privacyMode={privacyMode} mask={mask} />
            </TableBody>
          </Table>
        </div>
      )}

      {cryptoHoldings.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-3 pt-2 border-t border-border">
            <div className="flex items-center gap-2">
              <Bitcoin className="h-4 w-4 text-orange-400" />
              <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">Crypto</h3>
            </div>
          </div>
          <div className="overflow-x-auto -mx-2 sm:mx-0">
            <Table>
              {tableHeader(true)}
              <TableBody>
                <HoldingsRows holdings={cryptoHoldings} accountNames={accountNames} privacyMode={privacyMode} mask={mask} isCrypto />
              </TableBody>
            </Table>
          </div>
        </div>
      )}
    </div>
  );
}
