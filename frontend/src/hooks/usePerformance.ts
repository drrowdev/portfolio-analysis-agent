import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { PerformanceResponse } from '@/types/portfolio';

export function usePerformance(period: string) {
  return useQuery<PerformanceResponse>({
    queryKey: ['portfolio', 'performance', period],
    queryFn: () => api.get(`/portfolio/performance?period=${period}`),
    staleTime: 2 * 60 * 60 * 1000, // 2 hours — matches backend DB cache TTL
    gcTime: 4 * 60 * 60 * 1000,    // keep in memory 4 hours
    retry: false,
  });
}
