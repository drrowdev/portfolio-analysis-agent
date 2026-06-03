import { useState, useMemo, useCallback } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useAccounts } from '@/hooks/useAccounts';
import { useHoldings } from '@/hooks/usePortfolio';
import { api } from '@/lib/api';
import { formatDate } from '@/lib/utils';
import { toast } from '@/hooks/useToast';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Loader2 } from 'lucide-react';
import { TaxCalculationDialog } from './TaxCalculationDialog';

interface QuickTradeDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function QuickTradeDialog({ open, onOpenChange }: QuickTradeDialogProps) {
  const { data: accounts = [] } = useAccounts();
  const { data: holdings = [] } = useHoldings();
  const queryClient = useQueryClient();

  const [tradeType, setTradeType] = useState<'buy' | 'sell'>('buy');
  const [accountId, setAccountId] = useState('');
  const [symbol, setSymbol] = useState('');
  const [name, setName] = useState('');
  const [quantity, setQuantity] = useState('');
  const [price, setPrice] = useState('');
  const [currency, setCurrency] = useState<'EUR' | 'USD'>('EUR');
  const [tradeDate, setTradeDate] = useState(new Date().toISOString().slice(0, 10));
  const [fees, setFees] = useState('');
  const [feesCurrency, setFeesCurrency] = useState<'EUR' | 'USD'>('EUR');
  const [feesCurrencyTouched, setFeesCurrencyTouched] = useState(false);
  const [nameLooking, setNameLooking] = useState(false);
  const [taxDialogOpen, setTaxDialogOpen] = useState(false);
  const [taxSellParams, setTaxSellParams] = useState<{
    symbol: string;
    quantity: number;
    sell_price_eur: number;
    sell_date: string;
    fees_eur: number;
  } | null>(null);

  const { data: fxData } = useQuery({
    queryKey: ['fx', 'eurusd', tradeDate],
    queryFn: () => api.getFxRate(tradeDate),
    enabled: (currency === 'USD' || feesCurrency === 'USD') && !!tradeDate,
    staleTime: 24 * 60 * 60 * 1000,  // historical rates don't change
  });

  const fxRate = fxData?.rate ?? null;

  const lookupSymbolName = useCallback(async (sym: string) => {
    if (!sym.trim()) return;
    setNameLooking(true);
    try {
      const result = await api.get<{ symbol: string; name: string }>(`/holdings/symbol-info?symbol=${encodeURIComponent(sym.trim())}`);
      setName(result.name);
    } catch {
      // Leave name empty — user can type manually
    } finally {
      setNameLooking(false);
    }
  }, []);

  const accountHoldings = useMemo(
    () => (accountId ? holdings.filter((h) => h.account_id === accountId) : []),
    [holdings, accountId],
  );

  const total = useMemo(() => {
    const q = parseFloat(quantity);
    const p = parseFloat(price);
    return q > 0 && p > 0 ? q * p : 0;
  }, [quantity, price]);

  const eurPrice = useMemo(() => {
    if (currency === 'EUR') return parseFloat(price) || 0;
    if (!fxRate) return 0;
    return (parseFloat(price) || 0) / fxRate;
  }, [currency, price, fxRate]);

  const eurTotal = useMemo(() => {
    const q = parseFloat(quantity) || 0;
    return q * eurPrice;
  }, [quantity, eurPrice]);

  const eurFees = useMemo(() => {
    const f = parseFloat(fees) || 0;
    if (feesCurrency === 'EUR') return f;
    if (!fxRate) return 0;
    return f / fxRate;
  }, [feesCurrency, fees, fxRate]);

  // When the user changes the trade currency, default fees currency to match
  // (until the user explicitly picks a fees currency themselves).
  const handleCurrencyChange = useCallback((next: 'EUR' | 'USD') => {
    setCurrency(next);
    if (!feesCurrencyTouched) setFeesCurrency(next);
  }, [feesCurrencyTouched]);

  const handleFeesCurrencyChange = useCallback((next: 'EUR' | 'USD') => {
    setFeesCurrency(next);
    setFeesCurrencyTouched(true);
  }, []);

  const mutation = useMutation({
    mutationFn: api.quickTrade,
    onSuccess: (result: { status: string; tax_filing_required?: boolean }, variables) => {
      queryClient.invalidateQueries({ queryKey: ['holdings'] });
      queryClient.invalidateQueries({ queryKey: ['portfolio'] });
      queryClient.invalidateQueries({ queryKey: ['accounts'] });
      toast({
        title: `${variables.trade_type === 'buy' ? 'Bought' : 'Sold'} ${variables.quantity} × ${variables.symbol}`,
      });

      // tax dialog wants the fees value in EUR (already converted above)
      if (result.tax_filing_required && variables.trade_type === 'sell') {
        setTaxSellParams({
          symbol: variables.symbol,
          quantity: variables.quantity,
          sell_price_eur: variables.price_per_share_eur,
          sell_date: variables.trade_date || new Date().toISOString().slice(0, 10),
          fees_eur: variables.fees || 0,
        });
        setTaxDialogOpen(true);
      }

      resetAndClose();
    },
    onError: (err: Error) => {
      toast({ title: 'Trade failed', description: err.message, variant: 'destructive' });
    },
  });

  function resetAndClose() {
    setTradeType('buy');
    setAccountId('');
    setSymbol('');
    setName('');
    setQuantity('');
    setPrice('');
    setCurrency('EUR');
    setTradeDate(new Date().toISOString().slice(0, 10));
    setFees('');
    setFeesCurrency('EUR');
    setFeesCurrencyTouched(false);
    onOpenChange(false);
  }

  function handleSellSymbolChange(sym: string) {
    setSymbol(sym);
    const h = accountHoldings.find((h) => h.symbol === sym);
    if (h) setName(h.instrument_name);
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!accountId || !symbol || !name || !quantity || !price) return;

    // Guard against the Enter-key path submitting a USD trade before the
    // sale-day EUR/USD rate has loaded — otherwise the USD price would be
    // treated as EUR (priceEur fallback below), inflating the tax basis.
    const needsFx =
      currency === 'USD' || (feesCurrency === 'USD' && parseFloat(fees) > 0);
    if (needsFx && !fxRate) {
      toast({
        title: 'Waiting for exchange rate',
        description: `Fetching the EUR/USD rate for ${tradeDate}. Try again in a moment.`,
        variant: 'destructive',
      });
      return;
    }

    const priceEur = currency === 'USD' && fxRate
      ? parseFloat(price) / fxRate
      : parseFloat(price);

    mutation.mutate({
      account_id: accountId,
      symbol: symbol.toUpperCase(),
      instrument_name: name,
      currency: currency,
      trade_type: tradeType,
      quantity: parseFloat(quantity),
      price_per_share_eur: priceEur,
      price_per_share_native: parseFloat(price) || undefined,
      fx_rate: currency === 'USD' && fxRate ? fxRate : undefined,
      trade_date: tradeDate,
      fees: eurFees,
    });
  }

  const isValid = accountId && symbol && name && parseFloat(quantity) > 0 && parseFloat(price) > 0
    && (currency === 'EUR' || fxRate !== null)
    && (feesCurrency === 'EUR' || !parseFloat(fees) || fxRate !== null);

  return (
    <>
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Record Trade</DialogTitle>
          <DialogDescription>Quickly log a buy or sell without uploading a CSV.</DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Trade type toggle */}
          <div className="flex gap-2">
            <Button
              type="button"
              variant={tradeType === 'buy' ? 'default' : 'outline'}
              className={
                tradeType === 'buy'
                  ? 'flex-1 bg-emerald-600 hover:bg-emerald-700 text-white'
                  : 'flex-1'
              }
              onClick={() => {
                setTradeType('buy');
                setSymbol('');
                setName('');
              }}
            >
              Buy
            </Button>
            <Button
              type="button"
              variant={tradeType === 'sell' ? 'destructive' : 'outline'}
              className="flex-1"
              onClick={() => {
                setTradeType('sell');
                setSymbol('');
                setName('');
              }}
            >
              Sell
            </Button>
          </div>

          {/* Account */}
          <div className="space-y-1.5">
            <label className="text-sm font-medium">Account</label>
            <Select value={accountId} onValueChange={setAccountId}>
              <SelectTrigger>
                <SelectValue placeholder="Select account" />
              </SelectTrigger>
              <SelectContent>
                {accounts.map((a) => (
                  <SelectItem key={a.id} value={a.id}>
                    {a.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Symbol */}
          <div className="space-y-1.5">
            <label className="text-sm font-medium">Symbol</label>
            {tradeType === 'sell' && accountHoldings.length > 0 ? (
              <Select value={symbol} onValueChange={handleSellSymbolChange}>
                <SelectTrigger>
                  <SelectValue placeholder="Select holding" />
                </SelectTrigger>
                <SelectContent>
                  {accountHoldings.map((h) => (
                    <SelectItem key={h.id} value={h.symbol}>
                      {h.symbol} — {h.instrument_name} ({h.total_quantity} held)
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : (
              <Input
                placeholder="e.g. NVDA"
                value={symbol}
                onChange={(e) => setSymbol(e.target.value)}
                onBlur={() => {
                  if (symbol.trim() && !name) lookupSymbolName(symbol);
                }}
              />
            )}
          </div>

          {/* Name (auto-filled from symbol lookup) */}
          <div className="space-y-1.5">
            <label className="text-sm font-medium">Instrument Name</label>
            <div className="relative">
              <Input
                placeholder="Auto-filled from symbol"
                value={name}
                onChange={(e) => setName(e.target.value)}
                disabled={nameLooking}
              />
              {nameLooking && (
                <Loader2 className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 animate-spin text-muted-foreground" />
              )}
            </div>
          </div>

          {/* Quantity & Price */}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <label className="text-sm font-medium">Quantity</label>
              <Input
                type="number"
                min="0"
                step="any"
                placeholder="0"
                value={quantity}
                onChange={(e) => setQuantity(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <label className="text-sm font-medium">
                  Price / share {currency === 'EUR' ? '(€)' : '($)'}
                </label>
                <div className="flex rounded-md border overflow-hidden">
                  <button
                    type="button"
                    className={`px-2 py-0.5 text-xs font-medium transition-colors ${
                      currency === 'EUR'
                        ? 'bg-primary text-primary-foreground'
                        : 'bg-transparent text-muted-foreground hover:text-foreground'
                    }`}
                    onClick={() => handleCurrencyChange('EUR')}
                  >
                    €
                  </button>
                  <button
                    type="button"
                    className={`px-2 py-0.5 text-xs font-medium transition-colors ${
                      currency === 'USD'
                        ? 'bg-primary text-primary-foreground'
                        : 'bg-transparent text-muted-foreground hover:text-foreground'
                    }`}
                    onClick={() => handleCurrencyChange('USD')}
                  >
                    $
                  </button>
                </div>
              </div>
              <Input
                type="number"
                min="0"
                step="any"
                placeholder="0.00"
                value={price}
                onChange={(e) => setPrice(e.target.value)}
              />
              {currency === 'USD' && parseFloat(price) > 0 && fxRate && (
                <p className="text-xs text-muted-foreground">
                  ≈ €{eurPrice.toFixed(2)} (rate on {formatDate(tradeDate)}: 1 EUR = {fxRate.toFixed(4)} USD)
                </p>
              )}
            </div>
          </div>

          {/* Date & Commission */}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <label className="text-sm font-medium">Trade Date</label>
              <Input
                type="date"
                value={tradeDate}
                onChange={(e) => setTradeDate(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <label className="text-sm font-medium">
                  Commission {feesCurrency === 'EUR' ? '(€)' : '($)'}
                </label>
                <div className="flex rounded-md border overflow-hidden">
                  <button
                    type="button"
                    className={`px-2 py-0.5 text-xs font-medium transition-colors ${
                      feesCurrency === 'EUR'
                        ? 'bg-primary text-primary-foreground'
                        : 'bg-transparent text-muted-foreground hover:text-foreground'
                    }`}
                    onClick={() => handleFeesCurrencyChange('EUR')}
                  >
                    €
                  </button>
                  <button
                    type="button"
                    className={`px-2 py-0.5 text-xs font-medium transition-colors ${
                      feesCurrency === 'USD'
                        ? 'bg-primary text-primary-foreground'
                        : 'bg-transparent text-muted-foreground hover:text-foreground'
                    }`}
                    onClick={() => handleFeesCurrencyChange('USD')}
                  >
                    $
                  </button>
                </div>
              </div>
              <Input
                type="number"
                min="0"
                step="any"
                placeholder="0.00"
                value={fees}
                onChange={(e) => setFees(e.target.value)}
              />
              {feesCurrency === 'USD' && parseFloat(fees) > 0 && fxRate && (
                <p className="text-xs text-muted-foreground">
                  ≈ €{eurFees.toFixed(2)}
                </p>
              )}
            </div>
          </div>

          {/* Total */}
          {total > 0 && (
            <div className="rounded-md bg-muted px-4 py-3 text-center">
              <span className="text-xs text-muted-foreground">Total</span>
              {currency === 'EUR' ? (
                <p className="text-lg font-semibold">
                  €{total.toLocaleString('fi-FI', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </p>
              ) : (
                <p className="text-lg font-semibold">
                  ${total.toLocaleString('fi-FI', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  {fxRate && (
                    <span className="text-sm font-normal text-muted-foreground">
                      {' '}≈ €{eurTotal.toLocaleString('fi-FI', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </span>
                  )}
                </p>
              )}
            </div>
          )}

          {/* Actions */}
          <div className="flex justify-end gap-2 pt-1">
            <Button type="button" variant="outline" onClick={resetAndClose}>
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={!isValid || mutation.isPending}
              className={
                tradeType === 'buy'
                  ? 'bg-emerald-600 hover:bg-emerald-700'
                  : ''
              }
              variant={tradeType === 'sell' ? 'destructive' : 'default'}
            >
              {mutation.isPending ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Submitting…
                </>
              ) : tradeType === 'buy' ? (
                'Buy'
              ) : (
                'Sell'
              )}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
    <TaxCalculationDialog
      open={taxDialogOpen}
      onOpenChange={setTaxDialogOpen}
      sellParams={taxSellParams}
    />
    </>
  );
}
