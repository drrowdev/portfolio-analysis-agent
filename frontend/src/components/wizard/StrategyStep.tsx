import { useState } from 'react';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Plus, Trash2, AlertCircle } from 'lucide-react';
import { cn } from '@/lib/utils';
import { DEFAULT_STRATEGY_FORM } from '@/types/strategy';
import type { StrategyFormData, RiskTolerance } from '@/types/strategy';

interface StrategyStepProps {
  onChange?: (data: StrategyFormData) => void;
  initialData?: StrategyFormData;
}

const RISK_OPTIONS: { value: RiskTolerance; label: string; description: string }[] = [
  { value: 'conservative', label: 'Conservative', description: 'Lower risk, steadier returns' },
  { value: 'moderate', label: 'Moderate', description: 'Balanced risk and return' },
  { value: 'aggressive', label: 'Aggressive', description: 'Higher risk, higher potential returns' },
];

export function StrategyStep({ onChange, initialData }: StrategyStepProps) {
  const [form, setForm] = useState<StrategyFormData>(initialData ?? DEFAULT_STRATEGY_FORM);

  function update(partial: Partial<StrategyFormData>) {
    const next = { ...form, ...partial };
    setForm(next);
    onChange?.(next);
  }

  function updateAllocation(
    index: number,
    field: 'category' | 'percentage',
    value: string | number,
  ) {
    const newAllocations = form.allocations.map((a, i) =>
      i === index
        ? { ...a, [field]: field === 'percentage' ? (Number(value) || 0) : value }
        : a,
    );
    update({ allocations: newAllocations });
  }

  function addAllocation() {
    update({ allocations: [...form.allocations, { category: '', percentage: 0 }] });
  }

  function removeAllocation(index: number) {
    update({ allocations: form.allocations.filter((_, i) => i !== index) });
  }

  const totalPct = form.allocations.reduce((sum, a) => sum + a.percentage, 0);

  return (
    <div className="space-y-5">
      <p className="text-sm text-muted-foreground">
        Configure your investment strategy so the AI agent can provide tailored recommendations.
      </p>

      {/* Strategy Name */}
      <div>
        <label className="text-sm font-medium text-foreground">Strategy Name</label>
        <Input
          value={form.name}
          onChange={(e) => update({ name: e.target.value })}
          placeholder="My Investment Strategy"
          className="mt-1"
        />
      </div>

      {/* Description */}
      <div>
        <label className="text-sm font-medium text-foreground">
          Investment Goal / Description
        </label>
        <textarea
          value={form.description}
          onChange={(e) => update({ description: e.target.value })}
          className="mt-1 flex min-h-[80px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          placeholder="e.g., Long-term wealth building for retirement with focus on global diversification"
        />
      </div>

      {/* Risk Tolerance */}
      <div>
        <label className="text-sm font-medium text-foreground">Risk Tolerance</label>
        <div className="mt-2 grid grid-cols-3 gap-3">
          {RISK_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => update({ riskTolerance: opt.value })}
              className={cn(
                'rounded-lg border p-3 text-left transition-colors',
                form.riskTolerance === opt.value
                  ? 'border-emerald-500 bg-emerald-600/10 ring-1 ring-emerald-500'
                  : 'border-border hover:bg-accent',
              )}
            >
              <div className="text-sm font-medium">{opt.label}</div>
              <div className="text-xs text-muted-foreground">{opt.description}</div>
            </button>
          ))}
        </div>
      </div>

      {/* Target Allocation */}
      <div>
        <div className="flex items-center justify-between">
          <label className="text-sm font-medium text-foreground">Target Allocation</label>
          <span
            className={cn(
              'text-xs font-medium',
              totalPct === 100 ? 'text-emerald-500' : 'text-amber-500',
            )}
          >
            Total: {totalPct}%
          </span>
        </div>
        <div className="mt-2 space-y-2">
          {form.allocations.map((alloc, i) => (
            <div key={i} className="flex items-center gap-2">
              <Input
                value={alloc.category}
                onChange={(e) => updateAllocation(i, 'category', e.target.value)}
                placeholder="Category name"
                className="flex-1"
              />
              <div className="flex items-center gap-1">
                <Input
                  type="number"
                  value={alloc.percentage}
                  onChange={(e) => updateAllocation(i, 'percentage', e.target.value)}
                  className="w-20 text-right"
                  min={0}
                  max={100}
                />
                <span className="text-sm text-muted-foreground">%</span>
              </div>
              {form.allocations.length > 1 && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => removeAllocation(i)}
                  className="h-9 w-9 p-0 text-muted-foreground hover:text-destructive"
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              )}
            </div>
          ))}
          <Button variant="outline" size="sm" onClick={addAllocation} className="mt-1">
            <Plus className="mr-1 h-3 w-3" />
            Add Category
          </Button>
        </div>
        {totalPct !== 100 && (
          <div className="mt-2 flex items-center gap-1 text-xs text-amber-500">
            <AlertCircle className="h-3 w-3" />
            Percentages should sum to 100%
          </div>
        )}
      </div>

      {/* Rebalance Threshold */}
      <div>
        <label className="text-sm font-medium text-foreground">Rebalance Threshold</label>
        <p className="text-xs text-muted-foreground mt-0.5">
          Trigger rebalance alert when allocation drifts more than this percentage
        </p>
        <div className="flex items-center gap-2 mt-1">
          <Input
            type="number"
            value={form.rebalanceThreshold}
            onChange={(e) => update({ rebalanceThreshold: Number(e.target.value) || 0 })}
            className="w-24"
            min={1}
            max={50}
          />
          <span className="text-sm text-muted-foreground">%</span>
        </div>
      </div>

      {/* Tax Optimization */}
      <div className="flex items-start gap-3">
        <input
          type="checkbox"
          checked={form.taxOptimization}
          onChange={(e) => update({ taxOptimization: e.target.checked })}
          className="mt-1 h-4 w-4 rounded border-input accent-emerald-600"
          id="tax-opt"
        />
        <div>
          <label htmlFor="tax-opt" className="text-sm font-medium text-foreground cursor-pointer">
            Enable Tax Optimization
          </label>
          <p className="text-xs text-muted-foreground">
            Enable Finnish tax-aware recommendations (AOT/OST/ESPP)
          </p>
        </div>
      </div>

      {/* Monthly Budget */}
      <div>
        <label className="text-sm font-medium text-foreground">
          Monthly Investment Budget (EUR)
        </label>
        <div className="flex items-center gap-2 mt-1">
          <span className="text-sm text-muted-foreground">€</span>
          <Input
            type="number"
            value={form.monthlyBudget}
            onChange={(e) => update({ monthlyBudget: e.target.value })}
            placeholder="e.g., 500"
            className="w-36"
            min={0}
          />
        </div>
      </div>

      {/* Custom Rules */}
      <div>
        <label className="text-sm font-medium text-foreground">
          Additional Notes / Custom Rules
        </label>
        <textarea
          value={form.customRules}
          onChange={(e) => update({ customRules: e.target.value })}
          className="mt-1 flex min-h-[80px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          placeholder="Any other preferences, constraints, or rules..."
        />
      </div>
    </div>
  );
}
