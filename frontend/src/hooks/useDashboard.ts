import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect } from 'react';
import { api } from '@/lib/api';
import type { PortfolioSummary, Holding, Account } from '@/types/portfolio';
import type { MarketStatusResponse } from '@/lib/api';
import type { AnalysisHistoryItem } from '@/hooks/useAnalysis';

interface DashboardData {
  summary: PortfolioSummary;
  holdings: Holding[];
  accounts: Account[];
  market_status: MarketStatusResponse;
  daily_summary: AnalysisHistoryItem | null;
}

export function useDashboard() {
  const queryClient = useQueryClient();
  const query = useQuery<DashboardData>({
    queryKey: ['dashboard'],
    queryFn: () => api.get('/dashboard'),
    staleTime: 5 * 60_000, // 5 min — server caches 60s, prices update every 5 min
    gcTime: 10 * 60_000,
  });

  // Seed individual query caches so child components that still use
  // usePortfolioSummary/useHoldings/etc. get instant hits.
  useEffect(() => {
    if (query.data) {
      queryClient.setQueryData(['portfolio', 'summary'], query.data.summary);
      queryClient.setQueryData(['holdings'], query.data.holdings);
      queryClient.setQueryData(['accounts'], query.data.accounts);
      queryClient.setQueryData(['market-status'], query.data.market_status);
      queryClient.setQueryData(['analysis', 'latest-daily-summary'], query.data.daily_summary);
    }
  }, [query.data, queryClient]);

  return query;
}
