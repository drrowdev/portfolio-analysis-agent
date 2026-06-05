import { coerceNumbers } from './utils';

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? '/api/v1';
const TOKEN_STORAGE_KEY = 'paa_token';

function storedToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

function setStoredToken(token: string | null): void {
  try {
    if (token) {
      localStorage.setItem(TOKEN_STORAGE_KEY, token);
    } else {
      localStorage.removeItem(TOKEN_STORAGE_KEY);
    }
  } catch {
    // ignore — storage may be unavailable
  }
}

function authHeaders(): Record<string, string> {
  const token = storedToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const url = `${API_BASE}${endpoint}`;
  const res = await fetch(url, {
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...authHeaders(),
      ...options?.headers,
    },
    ...options,
  });

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || `API error: ${res.status}`);
  }

  // 204 No Content (e.g. DELETE) or any empty body has nothing to parse.
  if (res.status === 204) {
    return undefined as T;
  }
  const text = await res.text();
  if (!text) {
    return undefined as T;
  }
  const data = JSON.parse(text);
  return coerceNumbers(data) as T;
}

async function uploadFormData<T>(endpoint: string, formData: FormData): Promise<T> {
  const url = `${API_BASE}${endpoint}`;
  const res = await fetch(url, {
    method: 'POST',
    credentials: 'include',
    headers: { ...authHeaders() },
    body: formData,
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || `Upload error: ${res.status}`);
  }
  const data = await res.json();
  return coerceNumbers(data) as T;
}

export const api = {
  get: <T>(endpoint: string) => request<T>(endpoint),

  post: <T>(endpoint: string, body: unknown) =>
    request<T>(endpoint, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  put: <T>(endpoint: string, body: unknown) =>
    request<T>(endpoint, {
      method: 'PUT',
      body: JSON.stringify(body),
    }),

  patch: <T>(endpoint: string, body: unknown) =>
    request<T>(endpoint, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),

  delete: <T>(endpoint: string) =>
    request<T>(endpoint, { method: 'DELETE' }),

  checkAuth: () => request<{ authenticated: boolean }>('/auth/check'),

  login: async (password: string) => {
    const res = await request<{ status: string; token?: string }>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ password }),
    });
    if (res.token) {
      setStoredToken(res.token);
    }
    return res;
  },

  clearAuth: () => setStoredToken(null),

  fetchPortfolioSummary: () =>
    request<unknown>('/portfolio/summary'),

  uploadNordnet: async <T>(file: File, accountType: 'arvo_osuustili' | 'osakesaastotili'): Promise<T> => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('account_type', accountType);
    return uploadFormData<T>('/upload/nordnet', formData);
  },

  uploadFidelity: async <T>(file: File): Promise<T> => {
    const formData = new FormData();
    formData.append('file', file);
    return uploadFormData<T>('/upload/fidelity', formData);
  },

  fetchLatestDailySummary: () => request<import('@/hooks/useAnalysis').AnalysisHistoryItem | null>('/analysis/latest-daily-summary'),

  triggerDailySummary: () => request<import('@/hooks/useAnalysis').AnalysisContent>('/analysis/daily-summary', { method: 'POST' }),

  fetchMarketStatus: () => request<MarketStatusResponse>('/market-status'),

  refreshPrices: () =>
    request<{ status: string }>('/portfolio/refresh-prices', { method: 'POST' }),

  quickTrade: (trade: {
    account_id: string;
    symbol: string;
    instrument_name: string;
    isin?: string;
    currency?: string;
    exchange?: string;
    trade_type: 'buy' | 'sell';
    quantity: number;
    price_per_share_eur: number;
    price_per_share_native?: number;
    fx_rate?: number;
    trade_date?: string;
    fees?: number;
  }) =>
    request<{ status: string; tax_filing_required?: boolean }>('/holdings/quick-trade', {
      method: 'POST',
      body: JSON.stringify(trade),
    }),

  getSetting: (key: string) =>
    request<{ key: string; value: string }>('/settings/' + key).catch(() => null),

  setSetting: (key: string, value: string) =>
    request<{ key: string; value: string }>('/settings/' + key, {
      method: 'PUT',
      body: JSON.stringify({ value }),
    }),

  getFxRate: (date?: string) => request<{ rate: number }>(`/fx/eurusd${date ? `?date=${encodeURIComponent(date)}` : ''}`),

  listTransactions: (params?: {
    account_id?: string;
    symbol?: string;
    transaction_type?: string;
    start_date?: string;
    end_date?: string;
    limit?: number;
    offset?: number;
  }) => {
    const query = new URLSearchParams();
    if (params) {
      Object.entries(params).forEach(([k, v]) => {
        if (v !== undefined && v !== '') query.set(k, String(v));
      });
    }
    const qs = query.toString();
    return request<import('@/types/portfolio').Transaction[]>(`/transactions/${qs ? '?' + qs : ''}`);
  },

  countTransactions: (params?: {
    account_id?: string;
    symbol?: string;
    transaction_type?: string;
    start_date?: string;
    end_date?: string;
  }) => {
    const query = new URLSearchParams();
    if (params) {
      Object.entries(params).forEach(([k, v]) => {
        if (v !== undefined && v !== '') query.set(k, String(v));
      });
    }
    const qs = query.toString();
    return request<{ count: number }>(`/transactions/count${qs ? '?' + qs : ''}`);
  },

  listTransactionSymbols: () => request<string[]>('/transactions/symbols'),

  // Tax calculations
  saveTaxCalculation: (payload: {
    symbol: string;
    sell_date: string;
    quantity_sold: string;
    sell_price_eur: string;
    fees_eur: string;
    calculation_json: Record<string, unknown>;
  }) => request<{ id: string; transaction_id: string | null }>('/transactions/tax-calculations/', {
    method: 'POST',
    body: JSON.stringify(payload),
  }),

  listTaxCalculations: (params?: { symbol?: string; year?: number }) => {
    const query = new URLSearchParams();
    if (params?.symbol) query.set('symbol', params.symbol);
    if (params?.year) query.set('year', String(params.year));
    const qs = query.toString();
    return request<
      {
        id: string;
        transaction_id: string | null;
        symbol: string;
        sell_date: string;
        declared: boolean;
        declared_at: string | null;
        paid_amount_eur: string | null;
        paid_date: string | null;
      }[]
    >(`/transactions/tax-calculations/${qs ? '?' + qs : ''}`);
  },

  setTaxCalculationDeclaration: (
    id: string,
    body: { declared: boolean; paid_amount_eur?: string | null; paid_date?: string | null }
  ) =>
    request<{ id: string; declared: boolean; paid_amount_eur: string | null; paid_date: string | null }>(
      `/transactions/tax-calculations/${id}/declaration`,
      { method: 'PATCH', body: JSON.stringify(body) }
    ),

  getDeclarationSummary: (year: number, symbol = 'MSFT') =>
    request<{
      year: number;
      symbol: string;
      sale_count: number;
      declared_count: number;
      paid_count: number;
      total_tax_eur: string;
      declared_tax_eur: string;
      remaining_tax_eur: string;
      total_paid_eur: string;
      computed_for_paid_eur: string;
      over_under_eur: string;
      fully_declared: boolean;
      sales: {
        id: string;
        sell_date: string;
        quantity_sold: string;
        computed_tax_eur: string;
        declared: boolean;
        declared_at: string | null;
        paid_amount_eur: string | null;
        paid_date: string | null;
      }[];
    }>(`/transactions/tax-calculations/declaration-summary?year=${year}&symbol=${symbol}`),

  getTaxCalculation: (id: string) =>
    request<{ id: string; calculation_json: Record<string, unknown> }>(`/transactions/tax-calculations/${id}`),

  getTaxCalculationByTransaction: (transactionId: string) =>
    request<{ id: string; calculation_json: Record<string, unknown> } | null>(
      `/transactions/tax-calculations/by-transaction/${transactionId}`
    ),

  getCapitalIncomeSummary: (year?: number) =>
    request<{
      year: number;
      taxable_gains_eur: number;
      gross_dividends_eur: number;
      taxable_dividends_eur: number;
      dividend_taxable_fraction: number;
      combined_taxable_eur: number;
      bracket_threshold_eur: number;
      remaining_at_low_rate_eur: number;
      amount_over_threshold_eur: number;
      estimated_tax_eur: number;
      effective_rate: number;
      low_rate: number;
      high_rate: number;
      sale_count: number;
      dividend_payment_count: number;
      excluded_ost_dividends_eur: number;
      excluded_ost_sale_count: number;
      sales: { symbol: string; sell_date: string; quantity: number; proceeds_eur: number; gain_eur: number }[];
      dividends: { symbol: string; gross_eur: number; taxable_eur: number; payments: number }[];
    }>(`/transactions/capital-income-summary${year ? `?year=${year}` : ''}`),

  getTaxCalculationPdfUrl: (id: string) =>
    `${API_BASE}/transactions/tax-calculations/${id}/pdf`,

  deleteTaxCalculation: (id: string) =>
    request<void>(`/transactions/tax-calculations/${id}`, { method: 'DELETE' }),

  deleteAllTaxCalculations: (params?: { symbol?: string; year?: number }) => {
    const query = new URLSearchParams();
    if (params?.symbol) query.set('symbol', params.symbol);
    if (params?.year) query.set('year', String(params.year));
    const qs = query.toString();
    return request<{ deleted: number }>(
      `/transactions/tax-calculations/${qs ? '?' + qs : ''}`,
      { method: 'DELETE' }
    );
  },

  chatStream:async function* (
    message: string,
    history: { role: string; content: string }[],
  ): AsyncGenerator<string> {
    const url = `${API_BASE}/chat/stream`;
    const res = await fetch(url, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ message, history }),
    });
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(error.detail || `Chat error: ${res.status}`);
    }
    const reader = res.body!.getReader();
    const decoder = new TextDecoder();
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      yield decoder.decode(value, { stream: true });
    }
  },
};

export interface ExchangeStatus {
  name: string;
  code: string;
  status: string;
  current_time: string;
  session_info: string;
  next_open?: string;
}

export interface MarketStatusResponse {
  exchanges: ExchangeStatus[];
}
