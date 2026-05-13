export type RiskTolerance = 'conservative' | 'moderate' | 'aggressive';

export interface Strategy {
  id: string;
  name: string;
  description: string | null;
  target_allocation: Record<string, number>;
  risk_tolerance: RiskTolerance;
  rebalance_threshold_pct: number;
  tax_optimization_enabled: boolean;
  custom_rules: unknown[] | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface StrategyCreate {
  name: string;
  description?: string;
  target_allocation: Record<string, number>;
  risk_tolerance: RiskTolerance;
  rebalance_threshold_pct: number;
  tax_optimization_enabled: boolean;
  custom_rules?: unknown[] | null;
  is_active?: boolean;
}

export type StrategyUpdate = Partial<StrategyCreate>;

export interface AllocationRow {
  category: string;
  percentage: number;
}

export interface StrategyFormData {
  name: string;
  description: string;
  riskTolerance: RiskTolerance;
  allocations: AllocationRow[];
  rebalanceThreshold: number;
  taxOptimization: boolean;
  monthlyBudget: string;
  customRules: string;
}

export const DEFAULT_STRATEGY_FORM: StrategyFormData = {
  name: 'My Investment Strategy',
  description: '',
  riskTolerance: 'moderate',
  allocations: [
    { category: 'Global Equities', percentage: 70 },
    { category: 'Bonds', percentage: 20 },
    { category: 'Alternatives', percentage: 10 },
  ],
  rebalanceThreshold: 5,
  taxOptimization: true,
  monthlyBudget: '',
  customRules: '',
};

export function toStrategyCreate(form: StrategyFormData): StrategyCreate {
  const target_allocation: Record<string, number> = {};
  for (const alloc of form.allocations) {
    if (alloc.category.trim()) {
      const key = alloc.category.trim().toLowerCase().replace(/\s+/g, '_');
      target_allocation[key] = alloc.percentage;
    }
  }

  const custom_rules: string[] = [];
  if (form.monthlyBudget) {
    custom_rules.push(`monthly_budget_eur:${form.monthlyBudget}`);
  }
  if (form.customRules.trim()) {
    custom_rules.push(form.customRules.trim());
  }

  return {
    name: form.name,
    description: form.description || undefined,
    target_allocation,
    risk_tolerance: form.riskTolerance,
    rebalance_threshold_pct: form.rebalanceThreshold,
    tax_optimization_enabled: form.taxOptimization,
    custom_rules: custom_rules.length > 0 ? custom_rules : null,
    is_active: true,
  };
}

export function strategyToFormData(strategy: Strategy): StrategyFormData {
  const allocations = Object.entries(strategy.target_allocation).map(([key, pct]) => ({
    category: key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
    percentage: pct,
  }));

  let monthlyBudget = '';
  let customRules = '';
  if (strategy.custom_rules) {
    for (const rule of strategy.custom_rules) {
      if (typeof rule === 'string' && rule.startsWith('monthly_budget_eur:')) {
        monthlyBudget = rule.split(':')[1];
      } else if (typeof rule === 'string') {
        customRules += (customRules ? '\n' : '') + rule;
      }
    }
  }

  return {
    name: strategy.name,
    description: strategy.description ?? '',
    riskTolerance: strategy.risk_tolerance,
    allocations: allocations.length > 0 ? allocations : DEFAULT_STRATEGY_FORM.allocations,
    rebalanceThreshold: strategy.rebalance_threshold_pct,
    taxOptimization: strategy.tax_optimization_enabled,
    monthlyBudget,
    customRules,
  };
}
