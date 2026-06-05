import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { FileText, Calculator, Info, CheckCircle2, Download, Save, AlertTriangle, Receipt } from 'lucide-react';
import { toast } from '@/hooks/useToast';

interface SavedCalcMeta {
  id: string;
  declared: boolean;
  paid_amount_eur: string | null;
  paid_date: string | null;
}

interface TaxCalculationDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  sellParams: {
    symbol: string;
    quantity: number;
    sell_price_eur: number;
    sell_date: string;
    fees_eur: number;
  } | null;
  /** The saved calculation for this sale (if one exists), for declaration tracking. */
  existingCalc?: SavedCalcMeta | null;
}

interface TaxLot {
  purchase_date: string;
  quantity: number;
  cost_per_share_eur: number;
  lot_cost_eur: number;
  holding_days: number;
  holding_years: number;
  over_10_years: boolean;
  applied_deemed_rate?: string;
  method?: string;
}

interface TaxCalculation {
  symbol: string;
  sell_date: string;
  quantity_sold: number;
  sell_price_eur: number;
  fees_eur: number;
  fx_rate: number | null;
  omavero: {
    luovutushinta: number;
    hankintameno_todellinen: number;
    hankintameno_olettama: number;
    hankintameno_olettama_rate: string;
    hankintameno_kaytetty: number;
    recommended_method: string;
    luovutusvoitto: number;
    veron_maara: number;
    veroprosentti: string;
  };
  comparison: {
    fifo_cost_basis_eur: number;
    fifo_gain_eur: number;
    deemed_cost_eur: number;
    deemed_gain_eur: number;
    better_method: string;
    tax_savings_eur: number;
  };
  bracket?: {
    year: number;
    prior_ytd_income_eur: number;
    threshold_eur: number;
    headroom_before_sale_eur: number;
    this_sale_gain_eur: number;
    amount_taxed_at_low_eur: number;
    amount_taxed_at_high_eur: number;
    low_rate: number;
    high_rate: number;
    applies_high_rate: boolean;
    crosses_threshold: boolean;
    fully_above_threshold: boolean;
  };
  coverage?: {
    quantity_sold: number;
    quantity_covered: number;
    shortfall_qty: number;
  };
  lots_consumed: TaxLot[];
  notes: string[];
}

function formatDate(iso: string) {
  return iso.split('-').reverse().join('.');
}

function eur(n: number) {
  return n.toLocaleString('fi-FI', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function methodLabel(method: string, rate: string): string {
  if (method === 'hankintameno_olettama') return `Olettama ${rate}`;
  if (method === 'yhdistelma') return `Yhdistelmä ${rate}`;
  return 'Todellinen';
}

function pct(rate: number): string {
  return `${Math.round(rate * 100)} %`;
}

type Bracket = NonNullable<TaxCalculation['bracket']>;

/** Visualises where this sale's gain lands on the per-year €30k / 34% bracket. */
function BracketCard({ b }: { b: Bracket }) {
  const lowTax = b.amount_taxed_at_low_eur * b.low_rate;
  const highTax = b.amount_taxed_at_high_eur * b.high_rate;
  const totalTax = lowTax + highTax;
  const high = b.applies_high_rate;

  // Stacked bar: prior income (if positive) + this sale's 30% part + 34% part,
  // scaled so the whole stack (or at least the €30k threshold) fits the width.
  const priorPos = Math.max(b.prior_ytd_income_eur, 0);
  const scale = Math.max(priorPos + b.this_sale_gain_eur, b.threshold_eur) || 1;
  const w = (v: number) => `${Math.max(0, Math.min(100, (v / scale) * 100))}%`;
  const thresholdLeft = `${Math.min(100, (b.threshold_eur / scale) * 100)}%`;

  return (
    <div
      className={`rounded-lg border-2 p-4 ${
        high ? 'border-amber-500/50 bg-amber-500/10' : 'border-emerald-500/40 bg-emerald-500/5'
      }`}
    >
      {/* Header */}
      <div className="flex items-start gap-2 mb-3">
        {high ? (
          <AlertTriangle className="h-5 w-5 text-amber-400 mt-0.5 shrink-0" />
        ) : (
          <CheckCircle2 className="h-5 w-5 text-emerald-400 mt-0.5 shrink-0" />
        )}
        <div>
          <h3 className={`text-sm font-semibold ${high ? 'text-amber-300' : 'text-emerald-300'}`}>
            {high
              ? b.fully_above_threshold
                ? `Koko myynti verotetaan ${pct(b.high_rate)} mukaan`
                : `30 000 € raja ylittyy — osa myynnistä verotetaan ${pct(b.high_rate)} mukaan`
              : `Myynti pysyy ${pct(b.low_rate)} portaassa`}
          </h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            Vuoden {b.year} pääomatulot ennen tätä myyntiä{' '}
            <span className="font-mono font-semibold text-foreground">
              €{eur(b.prior_ytd_income_eur)}
            </span>{' '}
            / raja €{eur(b.threshold_eur)}
          </p>
        </div>
      </div>

      {/* Stacked bracket bar */}
      <div className="relative h-6 w-full rounded bg-background/50 overflow-hidden">
        {priorPos > 0 && (
          <div className="absolute inset-y-0 left-0 bg-muted-foreground/30" style={{ width: w(priorPos) }} />
        )}
        {b.amount_taxed_at_low_eur > 0 && (
          <div
            className="absolute inset-y-0 bg-sky-500/60"
            style={{ left: w(priorPos), width: w(b.amount_taxed_at_low_eur) }}
          />
        )}
        {b.amount_taxed_at_high_eur > 0 && (
          <div
            className="absolute inset-y-0 bg-amber-500/70"
            style={{ left: w(priorPos + b.amount_taxed_at_low_eur), width: w(b.amount_taxed_at_high_eur) }}
          />
        )}
        {/* €30k threshold marker */}
        <div className="absolute inset-y-0 border-l-2 border-dashed border-foreground/70" style={{ left: thresholdLeft }} />
      </div>
      <div className="flex justify-between text-[10px] text-muted-foreground mt-1 mb-3">
        <span>€0</span>
        <span className="font-medium text-foreground/70">↑ 30 000 €</span>
        <span>€{eur(scale)}</span>
      </div>

      {/* Breakdown */}
      <div className="space-y-1.5 text-xs">
        <div className="flex items-center justify-between">
          <span className="flex items-center gap-1.5 text-muted-foreground">
            <span className="inline-block h-2.5 w-2.5 rounded-sm bg-muted-foreground/30" />
            Aiemmat pääomatulot {b.year}
          </span>
          <span className="font-mono">€{eur(b.prior_ytd_income_eur)}</span>
        </div>
        {b.amount_taxed_at_low_eur > 0 && (
          <div className="flex items-center justify-between">
            <span className="flex items-center gap-1.5">
              <span className="inline-block h-2.5 w-2.5 rounded-sm bg-sky-500/60" />
              Tästä myynnistä {pct(b.low_rate)} verolla
            </span>
            <span className="font-mono">
              €{eur(b.amount_taxed_at_low_eur)}{' '}
              <span className="text-muted-foreground">→ vero €{eur(lowTax)}</span>
            </span>
          </div>
        )}
        {b.amount_taxed_at_high_eur > 0 && (
          <div className="flex items-center justify-between">
            <span className="flex items-center gap-1.5 text-amber-300">
              <span className="inline-block h-2.5 w-2.5 rounded-sm bg-amber-500/70" />
              Tästä myynnistä {pct(b.high_rate)} verolla
            </span>
            <span className="font-mono text-amber-300">
              €{eur(b.amount_taxed_at_high_eur)}{' '}
              <span className="opacity-70">→ vero €{eur(highTax)}</span>
            </span>
          </div>
        )}
        <div className="flex items-center justify-between border-t border-border/50 pt-1.5 font-semibold">
          <span>Ennakkovero tästä myynnistä</span>
          <span className="font-mono">€{eur(totalTax)}</span>
        </div>
        {!high && (
          <p className="text-[11px] text-muted-foreground pt-0.5">
            30 %:n rajaan jäljellä{' '}
            <span className="font-mono text-emerald-400">€{eur(b.headroom_before_sale_eur)}</span>{' '}
            ennen kuin korkeampi 34 %:n vero alkaa.
          </p>
        )}
      </div>
    </div>
  );
}

export function TaxCalculationDialog({ open, onOpenChange, sellParams, existingCalc }: TaxCalculationDialogProps) {
  const [savedId, setSavedId] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const { data: taxCalc, isLoading, error } = useQuery<TaxCalculation>({
    queryKey: ['tax-calculation', sellParams],
    queryFn: () => {
      if (!sellParams) throw new Error('No params');
      const params = new URLSearchParams({
        symbol: sellParams.symbol,
        quantity: String(sellParams.quantity),
        sell_price_eur: String(sellParams.sell_price_eur),
        sell_date: sellParams.sell_date,
        fees_eur: String(sellParams.fees_eur),
      });
      return api.get<TaxCalculation>(`/transactions/tax-calculation?${params}`);
    },
    enabled: open && !!sellParams,
    staleTime: Infinity,
  });

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!sellParams || !taxCalc) throw new Error('No data');
      const result = await api.saveTaxCalculation({
        symbol: sellParams.symbol,
        sell_date: sellParams.sell_date,
        quantity_sold: String(sellParams.quantity),
        sell_price_eur: String(sellParams.sell_price_eur),
        fees_eur: String(sellParams.fees_eur),
        calculation_json: taxCalc as unknown as Record<string, unknown>,
      });
      return result;
    },
    onSuccess: (data) => {
      setSavedId(data.id);
      queryClient.invalidateQueries({ queryKey: ['tax-calculations-list'] });
      queryClient.invalidateQueries({ queryKey: ['capital-income-summary'] });
      queryClient.invalidateQueries({ queryKey: ['declaration-summary'] });
      toast({ title: 'Saved', description: 'Tax calculation stored successfully.' });
    },
    onError: (err) => {
      toast({ title: 'Error', description: (err as Error).message, variant: 'destructive' });
    },
  });

  const handleDownloadPdf = () => {
    if (!savedId) return;
    const url = api.getTaxCalculationPdfUrl(savedId);
    window.open(url, '_blank');
  };

  // --- Declaration / paid tracking ------------------------------------------
  const effectiveId = savedId ?? existingCalc?.id ?? null;
  const computedTax = taxCalc?.omavero.veron_maara ?? 0;
  const today = new Date().toISOString().slice(0, 10);

  const [declChecked, setDeclChecked] = useState(false);
  const [paidAmount, setPaidAmount] = useState('');
  const [paidDate, setPaidDate] = useState(today);

  // Sync the declaration form whenever the dialog opens on a different sale or
  // its saved declaration state changes.
  useEffect(() => {
    if (!open) return;
    const declared = existingCalc?.declared ?? false;
    setDeclChecked(declared);
    setPaidAmount(
      existingCalc?.paid_amount_eur ??
        (computedTax ? computedTax.toFixed(2) : '')
    );
    setPaidDate(existingCalc?.paid_date ?? today);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, existingCalc?.id, existingCalc?.declared, existingCalc?.paid_amount_eur, existingCalc?.paid_date, computedTax]);

  const declMutation = useMutation({
    mutationFn: async () => {
      if (!effectiveId) throw new Error('Save the calculation first');
      return api.setTaxCalculationDeclaration(effectiveId, {
        declared: declChecked,
        paid_amount_eur: declChecked ? (paidAmount || computedTax.toFixed(2)) : null,
        paid_date: declChecked ? paidDate : null,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['declaration-summary'] });
      queryClient.invalidateQueries({ queryKey: ['tax-calculations-list'] });
      toast({
        title: declChecked ? 'Marked declared' : 'Cleared',
        description: declChecked
          ? 'Saved as declared & paid.'
          : 'Declaration cleared.',
      });
    },
    onError: (err) =>
      toast({ title: 'Error', description: (err as Error).message, variant: 'destructive' }),
  });

  const paidNum = Number(paidAmount || 0);
  const diffVsComputed = paidNum - computedTax;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileText className="h-5 w-5 text-blue-400" />
            Ennakkoveroilmoitus — {sellParams?.symbol}
          </DialogTitle>
          <DialogDescription>
            Finnish advance tax filing info for OmaVero
          </DialogDescription>
        </DialogHeader>

        {isLoading && (
          <div className="py-8 text-center text-muted-foreground">
            <Calculator className="h-8 w-8 mx-auto mb-2 animate-pulse" />
            Computing tax calculation…
          </div>
        )}

        {error && (
          <div className="py-4 text-center text-red-400">
            Failed to compute tax: {(error as Error).message}
          </div>
        )}

        {taxCalc && (
          <div className="space-y-5">
            {/* Coverage warning — sold more shares than recorded buy lots */}
            {taxCalc.coverage && taxCalc.coverage.shortfall_qty > 0 && (
              <div className="rounded-lg border-2 border-amber-500/40 bg-amber-500/10 p-3 text-xs text-amber-300">
                ⚠️ Vain {taxCalc.coverage.quantity_covered} / {taxCalc.coverage.quantity_sold} myydystä
                osakkeesta löytyy ostotapahtumista. Puuttuvalle {taxCalc.coverage.shortfall_qty} osakkeelle
                käytettiin 20 % hankintameno-olettamaa. Tarkista ostohistoria — todellinen hankintameno voi
                pienentää veroa.
              </div>
            )}

            {/* Sale Summary */}
            <div className="rounded-lg border border-border bg-muted/30 p-4">
              <h3 className="text-sm font-semibold mb-2 text-muted-foreground uppercase tracking-wide">
                Myynti / Sale
              </h3>
              <div className="grid grid-cols-2 gap-2 text-sm">
                <div className="text-muted-foreground">Päivämäärä</div>
                <div className="font-medium text-right">{formatDate(taxCalc.sell_date)}</div>
                <div className="text-muted-foreground">Määrä</div>
                <div className="font-medium text-right">{taxCalc.quantity_sold} kpl</div>
                <div className="text-muted-foreground">Hinta / kpl</div>
                <div className="font-medium text-right">€{eur(taxCalc.sell_price_eur)}</div>
                <div className="text-muted-foreground">Kulut</div>
                <div className="font-medium text-right">€{eur(taxCalc.fees_eur)}</div>
                {taxCalc.fx_rate && (
                  <>
                    <div className="text-muted-foreground">Valuuttakurssi</div>
                    <div className="font-medium text-right">{taxCalc.fx_rate.toFixed(4)} USD/EUR</div>
                  </>
                )}
              </div>
            </div>

            {/* 30k bracket positioning */}
            {taxCalc.bracket && <BracketCard b={taxCalc.bracket} />}

            {/* OmaVero Fields */}
            <div className="rounded-lg border-2 border-blue-500/30 bg-blue-500/5 p-4">
              <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
                <CheckCircle2 className="h-4 w-4 text-blue-400" />
                OmaVero — Täytettävät tiedot
              </h3>
              <div className="space-y-2">
                <div className="flex justify-between items-center py-1.5 border-b border-border/50">
                  <span className="text-sm">Luovutushinta</span>
                  <span className="font-mono font-bold text-lg">€{eur(taxCalc.omavero.luovutushinta)}</span>
                </div>
                <div className="flex justify-between items-center py-1.5 border-b border-border/50">
                  <div className="text-sm">
                    <span>Hankintameno</span>
                    <Badge variant="outline" className="ml-2 text-xs">
                      {methodLabel(
                        taxCalc.omavero.recommended_method,
                        taxCalc.omavero.hankintameno_olettama_rate
                      )}
                    </Badge>
                  </div>
                  <span className="font-mono font-bold text-lg">
                    €{eur(
                      taxCalc.omavero.hankintameno_kaytetty ??
                        (taxCalc.omavero.recommended_method === 'hankintameno_olettama'
                          ? taxCalc.omavero.hankintameno_olettama
                          : taxCalc.omavero.hankintameno_todellinen)
                    )}
                  </span>
                </div>
                <div className="flex justify-between items-center py-1.5 border-b border-border/50">
                  <span className="text-sm font-semibold">Luovutusvoitto</span>
                  <span className={`font-mono font-bold text-lg ${taxCalc.omavero.luovutusvoitto >= 0 ? 'text-red-400' : 'text-emerald-400'}`}>
                    €{eur(taxCalc.omavero.luovutusvoitto)}
                  </span>
                </div>
                <div className="flex justify-between items-center py-1.5">
                  <div className="text-sm">
                    <span className="font-semibold">Ennakkovero</span>
                    <span className="text-muted-foreground text-xs ml-2">({taxCalc.omavero.veroprosentti})</span>
                  </div>
                  <span className="font-mono font-bold text-xl text-amber-400">
                    €{eur(taxCalc.omavero.veron_maara)}
                  </span>
                </div>
              </div>
            </div>

            {/* Method Comparison */}
            <div className="rounded-lg border border-border p-4">
              <h3 className="text-sm font-semibold mb-2 text-muted-foreground uppercase tracking-wide">
                Laskentatapojen vertailu
              </h3>
              <div className="grid grid-cols-3 gap-2 text-xs">
                <div></div>
                <div className="text-center font-medium">Todellinen (FIFO)</div>
                <div className="text-center font-medium">Olettama ({taxCalc.omavero.hankintameno_olettama_rate})</div>

                <div className="text-muted-foreground">Hankintameno</div>
                <div className={`text-center font-mono ${taxCalc.comparison.better_method === 'actual' ? 'text-emerald-400 font-bold' : ''}`}>
                  €{eur(taxCalc.comparison.fifo_cost_basis_eur)}
                </div>
                <div className={`text-center font-mono ${taxCalc.comparison.better_method === 'deemed' ? 'text-emerald-400 font-bold' : ''}`}>
                  €{eur(taxCalc.comparison.deemed_cost_eur)}
                </div>

                <div className="text-muted-foreground">Voitto</div>
                <div className="text-center font-mono">€{eur(taxCalc.comparison.fifo_gain_eur)}</div>
                <div className="text-center font-mono">€{eur(taxCalc.comparison.deemed_gain_eur)}</div>
              </div>
              {taxCalc.comparison.tax_savings_eur > 0 && (
                <p className="mt-2 text-xs text-emerald-400">
                  💡 Using {taxCalc.comparison.better_method === 'deemed' ? 'hankintameno-olettama' : 'actual cost'} saves
                  ~€{eur(taxCalc.comparison.tax_savings_eur)} in tax
                </p>
              )}
            </div>

            {/* FIFO Lots */}
            {taxCalc.lots_consumed.length > 0 && (
              <div className="rounded-lg border border-border p-4">
                <h3 className="text-sm font-semibold mb-2 text-muted-foreground uppercase tracking-wide">
                  Myydyt erät (FIFO)
                </h3>
                <div className="space-y-1">
                  {taxCalc.lots_consumed.map((lot, i) => (
                    <div key={i} className="flex justify-between text-xs py-1 border-b border-border/30 last:border-0">
                      <div>
                        <span className="font-mono">{lot.quantity}</span> kpl @ €{eur(lot.cost_per_share_eur)}
                        <span className="text-muted-foreground ml-1">({formatDate(lot.purchase_date)})</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="font-mono">€{eur(lot.lot_cost_eur)}</span>
                        {lot.applied_deemed_rate && (
                          <Badge
                            variant={lot.method === 'deemed' ? 'default' : 'secondary'}
                            className="text-[10px] px-1"
                          >
                            {lot.method === 'deemed' ? `Olettama ${lot.applied_deemed_rate}` : 'Todellinen'}
                          </Badge>
                        )}
                        <Badge variant={lot.over_10_years ? 'default' : 'secondary'} className="text-[10px] px-1">
                          {lot.holding_years}y
                        </Badge>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Notes */}
            <div className="rounded-lg border border-border/50 p-3">
              <div className="flex items-start gap-2">
                <Info className="h-4 w-4 text-muted-foreground mt-0.5 shrink-0" />
                <div className="space-y-1">
                  {taxCalc.notes.map((note, i) => (
                    <p key={i} className="text-xs text-muted-foreground">{note}</p>
                  ))}
                </div>
              </div>
            </div>

            {/* Action buttons */}
            <div className="flex gap-2 pt-2">
              <Button
                size="sm"
                variant={savedId ? 'secondary' : 'default'}
                onClick={() => saveMutation.mutate()}
                disabled={saveMutation.isPending || !!savedId}
              >
                {savedId ? (
                  <>
                    <CheckCircle2 className="h-4 w-4 mr-1" />
                    Saved
                  </>
                ) : (
                  <>
                    <Save className="h-4 w-4 mr-1" />
                    {saveMutation.isPending ? 'Saving…' : 'Save calculation'}
                  </>
                )}
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={handleDownloadPdf}
                disabled={!savedId}
              >
                <Download className="h-4 w-4 mr-1" />
                Download PDF
              </Button>
            </div>

            {/* Declaration / paid tracking */}
            <div className="rounded-lg border border-border bg-muted/20 p-4 space-y-3">
              <h3 className="text-sm font-semibold flex items-center gap-2">
                <Receipt className="h-4 w-4 text-muted-foreground" />
                Ennakkovero — ilmoitus & maksu
              </h3>

              {!effectiveId ? (
                <p className="text-xs text-muted-foreground">
                  Tallenna laskelma ensin, niin voit merkitä sen ilmoitetuksi ja maksetuksi.
                </p>
              ) : (
                <>
                  <label className="flex items-center gap-2 text-sm cursor-pointer">
                    <input
                      type="checkbox"
                      checked={declChecked}
                      onChange={(e) => setDeclChecked(e.target.checked)}
                      className="h-4 w-4 rounded border-border accent-emerald-500"
                    />
                    Ennakkovero ilmoitettu ja maksettu OmaVerossa
                  </label>

                  {declChecked && (
                    <div className="grid grid-cols-2 gap-3">
                      <div className="space-y-1">
                        <label className="text-xs text-muted-foreground">Maksettu määrä (€)</label>
                        <input
                          type="number"
                          step="0.01"
                          value={paidAmount}
                          onChange={(e) => setPaidAmount(e.target.value)}
                          className="w-full rounded-md border border-border bg-background px-2 py-1 text-sm font-mono"
                        />
                      </div>
                      <div className="space-y-1">
                        <label className="text-xs text-muted-foreground">Maksupäivä</label>
                        <input
                          type="date"
                          value={paidDate}
                          onChange={(e) => setPaidDate(e.target.value)}
                          className="w-full rounded-md border border-border bg-background px-2 py-1 text-sm"
                        />
                      </div>
                    </div>
                  )}

                  {declChecked && Math.abs(diffVsComputed) >= 0.01 && (
                    <p
                      className={`text-xs ${
                        diffVsComputed > 0 ? 'text-amber-400' : 'text-red-400'
                      }`}
                    >
                      {diffVsComputed > 0 ? 'Maksoit' : 'Maksoit'} €{eur(Math.abs(diffVsComputed))}{' '}
                      {diffVsComputed > 0 ? 'enemmän' : 'vähemmän'} kuin laskettu ennakkovero
                      (€{eur(computedTax)}). Verotuksen lopullinen tasaus huomioi erotuksen.
                    </p>
                  )}

                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => declMutation.mutate()}
                    disabled={declMutation.isPending}
                  >
                    <CheckCircle2 className="h-4 w-4 mr-1" />
                    {declMutation.isPending
                      ? 'Tallennetaan…'
                      : declChecked
                        ? 'Tallenna ilmoitus'
                        : 'Poista merkintä'}
                  </Button>
                </>
              )}
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
