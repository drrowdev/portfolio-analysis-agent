import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';

export interface NewsArticle {
  id: string;
  symbol: string | null;
  title: string;
  summary: string | null;
  url: string;
  source: string;
  published_at: string | null;
  sentiment_score: number | null;
  is_read: boolean;
  created_at: string | null;
}

export interface EarningsEntry {
  symbol: string;
  date: string | null;
  estimate_eps: number | null;
  actual_eps: number | null;
  revenue_estimate: number | null;
  quarter: number | null;
  year: number | null;
}

interface RefreshResponse {
  new_articles: number;
}

export function useNews(symbol?: string, limit?: number) {
  const params = new URLSearchParams();
  if (symbol) params.set('symbol', symbol);
  if (limit) params.set('limit', String(limit));
  const qs = params.toString();
  const endpoint = `/news/${qs ? `?${qs}` : ''}`;

  return useQuery<NewsArticle[]>({
    queryKey: ['news', symbol ?? 'all', limit ?? 50],
    queryFn: () => api.get(endpoint),
    staleTime: 60_000,
  });
}

export function useRefreshNews() {
  const queryClient = useQueryClient();
  return useMutation<RefreshResponse, Error>({
    mutationFn: () => api.post('/news/refresh', {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['news'] });
    },
  });
}

export function useEarningsCalendar() {
  return useQuery<EarningsEntry[]>({
    queryKey: ['news', 'earnings'],
    queryFn: () => api.get('/news/earnings'),
    staleTime: 300_000,
  });
}
