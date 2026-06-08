import { useState, useMemo, useEffect, useCallback } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { formatDate } from '@/lib/utils';
import { toast } from '@/hooks/useToast';
import type { Transaction } from '@/types/portfolio';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Loader2 } from 'lucide-react';

interface EditTransactionDialogProps {
  transaction: Transaction | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function EditTransactionDialog({ transaction, open, onOpenChange }: EditTransactionDialogProps) {
  const queryClient = useQueryClient();

  const [date, setDate] = useState('');
  const [quantity, setQuantity] = useState('');
  const [price, setPrice] = useState('');
  const [currency, setCurrency] = useState<'EUR' | 'USD'>('EUR');
  const [fees, setFees] = useState('');
  const [feesCurrency, setFeesCurrency] = useState<'EUR' | 'USD'>('EUR');
  const [fxRateOverride, setFxRateOverride] = useState('');
  const [notes, setNotes] = useState('');

  // Hydrate form from the incoming transaction
  useEffect(() => {
    if (!transaction) return;
    setDate(transaction.date.substring(0, 10));
    setQuantity(String(transaction.quantity));
    setPrice(String(transaction.price_native));
    setCurrency((transaction.currency as 'EUR' | 'USD') || 'EUR');
    setFees(transaction.fees ? String(transaction.fees) : '');
    // We don't know the fees' original currency; default to EUR (matches storage).
    setFeesCurrency('EUR');
    setFxRateOverride(transaction.fx_rate ? String(transaction.fx_rate) : '');
    setNotes(transaction.notes ?? '');
  }, [transaction]);

  // Fetch the FX rate for this trade date (USD only)
  const { data: fxData } = useQuery({
    queryKey: ['fx', 'eurusd', date],
    queryFn: () => api.getFxRate(date),
    enabled: open && !!date && (currency === 'USD' || feesCurrency === 'USD'),
    staleTime: 24 * 60 * 60 * 1000,
  });

  // Effective FX rate: user override beats the auto-fetched value
  const fxRate = useMemo(() => {
    const override = parseFloat(fxRateOverride);
    if (override > 0) return override;
    return fxData?.rate ?? null;
  }, [fxRateOverride, fxData]);

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

  const handleCurrencyChange = useCallback((next: 'EUR' | 'USD') => {
    setCurrency(next);
  }, []);
  const handleFeesCurrencyChange = useCallback((next: 'EUR' | 'USD') => {
    setFeesCurrency(next);
  }, []);

  const mutation = useMutation({
    mutationFn: (updates: Parameters<typeof api.updateTransaction>[1]) =>
      api.updateTransaction(transaction!.id, updates),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['transactions'] });
      queryClient.invalidateQueries({ queryKey: ['transactions-count'] });
      queryClient.invalidateQueries({ queryKey: ['holdings'] });
      queryClient.invalidateQueries({ queryKey: ['portfolio'] });
      queryClient.invalidateQueries({ queryKey: ['accounts'] });
      toast({ title: 'Transaction updated' });
      onOpenChange(false);
    },
    onError: (err: Error) => {
      toast({ title: 'Update failed', description: err.message, variant: 'destructive' });
    },
  });

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!transaction) return;
    const q = parseFloat(quantity);
    const p = parseFloat(price);
    if (!(q > 0) || !(p > 0)) return;
    if (currency === 'USD' && !fxRate) return;

    mutation.mutate({
      date,
      quantity: q,
      price_native: p,
      currency,
      fx_rate: currency === 'USD' && fxRate ? fxRate : null,
      // total_native gets recomputed server-side, but send it for clarity
      total_native: q * p,
      // Send EUR amounts explicitly so the server stores exactly what the
      // dialog showed the user (no rounding drift between client and server).
      price_eur: eurPrice,
      total_eur: eurTotal,
      fees: eurFees,
      notes: notes.trim() || null,
    });
  }

  const isValid =
    !!transaction &&
    !!date &&
    parseFloat(quantity) > 0 &&
    parseFloat(price) > 0 &&
    (currency === 'EUR' || fxRate !== null);

  if (!transaction) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Edit Transaction</DialogTitle>
          <DialogDescription>
            {transaction.transaction_type.toUpperCase()} · {transaction.symbol} · {transaction.instrument_name}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Date */}
          <div className="space-y-1.5">
            <label className="text-sm font-medium">Trade Date</label>
            <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
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
                  ≈ €{eurPrice.toFixed(2)} (rate on {formatDate(date)}: 1 EUR = {fxRate.toFixed(4)} USD)
                </p>
              )}
            </div>
          </div>

          {/* FX override (USD only) */}
          {currency === 'USD' && (
            <div className="space-y-1.5">
              <label className="text-sm font-medium">
                FX rate override <span className="text-xs text-muted-foreground">(optional — overrides auto-fetched rate)</span>
              </label>
              <Input
                type="number"
                min="0"
                step="any"
                placeholder={fxData?.rate ? fxData.rate.toFixed(4) : 'auto'}
                value={fxRateOverride}
                onChange={(e) => setFxRateOverride(e.target.value)}
              />
            </div>
          )}

          {/* Fees */}
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
              <p className="text-xs text-muted-foreground">≈ €{eurFees.toFixed(2)}</p>
            )}
          </div>

          {/* Notes */}
          <div className="space-y-1.5">
            <label className="text-sm font-medium">Notes</label>
            <Input
              placeholder="Optional note"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </div>

          {/* New totals preview */}
          {parseFloat(quantity) > 0 && parseFloat(price) > 0 && (
            <div className="rounded-md bg-muted px-4 py-3 text-center text-sm">
              <span className="text-xs text-muted-foreground">New total (EUR)</span>
              <p className="font-semibold">
                €{eurTotal.toLocaleString('fi-FI', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                {eurFees > 0 && (
                  <span className="text-muted-foreground font-normal">
                    {' '}+ €{eurFees.toFixed(2)} fees
                  </span>
                )}
              </p>
            </div>
          )}

          <div className="flex justify-end gap-2 pt-1">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={!isValid || mutation.isPending}>
              {mutation.isPending ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Saving…
                </>
              ) : (
                'Save'
              )}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
