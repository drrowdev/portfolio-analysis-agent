export type AccountType = 'arvo_osuustili' | 'osakesaastotili' | 'espp' | 'crypto';
export type TaxTreatment = 'standard' | 'deferred' | 'espp' | 'crypto';
export type AlertSeverity = 'info' | 'warning' | 'action';

export interface Account {
  id: string;
  name: string;
  broker: 'nordnet' | 'fidelity';
  account_type: AccountType;
  currency: string;
  tax_treatment: TaxTreatment;
}

export interface Holding {
  id: string;
  account_id: string;
  symbol: string;
  isin: string;
  instrument_name: string;
  currency: string;
  total_quantity: number;
  avg_cost_basis_eur: number;
  total_cost_eur: number;
  avg_cost_basis_native: number | null;
  total_cost_native: number | null;
  current_price_native: number | null;
  current_price_eur: number | null;
  current_value_eur: number | null;
  unrealized_pnl_eur: number | null;
  unrealized_pnl_pct: number | null;
  portfolio_weight_pct: number | null;
  price_change_pct: number | null;
  market_state: string | null;
  extended_hours_price: number | null;
  extended_hours_change_pct: number | null;
}

export interface AllocationEntry {
  symbol: string;
  instrument_name: string;
  weight_pct: number;
  value_eur: number;
}

export interface AccountSummary {
  account_id: string;
  account_name: string;
  broker: string;
  total_value_eur: number;
  total_cost_eur: number;
  unrealized_pnl_eur: number;
  unrealized_pnl_pct: number | null;
}

export interface PortfolioSummary {
  total_value_eur: number;
  total_cost_eur: number;
  total_unrealized_pnl_eur: number;
  total_unrealized_pnl_pct: number | null;
  daily_pnl_eur: number | null;
  daily_pnl_pct: number | null;
  accounts: AccountSummary[];
  top_holdings: AllocationEntry[];
  currency: string;
}

export interface UploadResponse {
  account_id: string;
  account_name: string;
  lots_imported: number;
  holdings_created: number;
  summary: PortfolioSummary;
}

export interface PerformanceDataPoint {
  date: string;
  portfolio_return_pct: number;
  sp500_return_pct: number;
  portfolio_value_eur: number;
}

export interface PerformanceResponse {
  period: string;
  start_date: string;
  data: PerformanceDataPoint[];
}

export type TransactionType = 'buy' | 'sell' | 'dividend' | 'espp_purchase' | 'espp_sale' | 'deposit' | 'withdrawal';

export interface Transaction {
  id: string;
  account_id: string;
  symbol: string;
  isin: string;
  instrument_name: string;
  currency: string;
  transaction_type: TransactionType;
  date: string;
  quantity: number;
  price_native: number;
  price_eur: number;
  total_native: number;
  total_eur: number;
  fx_rate: number | null;
  fees: number;
  notes: string | null;
  created_at: string;
}

export interface Alert {
  id: string;
  alert_type: string;
  title: string;
  message: string;
  severity: AlertSeverity;
  status: 'new' | 'read' | 'dismissed';
  related_symbol?: string;
  created_at: string;
}
