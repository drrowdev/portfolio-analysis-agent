import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';

export interface Alert {
  id: string;
  alert_type: 'price' | 'news' | 'earnings' | 'recommendation' | 'rebalance' | 'tax';
  title: string;
  message: string;
  severity: 'info' | 'warning' | 'action';
  status: 'new' | 'read' | 'dismissed';
  related_symbol: string | null;
  extra_data: Record<string, unknown>;
  created_at: string;
}

export function useAlerts(status?: string, limit = 50) {
  const params = new URLSearchParams();
  if (status) params.set('status', status);
  params.set('limit', String(limit));

  return useQuery<Alert[]>({
    queryKey: ['alerts', status, limit],
    queryFn: () => api.get(`/alerts/?${params.toString()}`),
    staleTime: 2 * 60_000, // 2 minutes
  });
}

export function useMarkAlertRead() {
  const queryClient = useQueryClient();
  return useMutation<unknown, Error, string>({
    mutationFn: (alertId) => api.put(`/alerts/${alertId}/read`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['alerts'] });
    },
  });
}

export function useDismissAlert() {
  const queryClient = useQueryClient();
  return useMutation<unknown, Error, string>({
    mutationFn: (alertId) => api.put(`/alerts/${alertId}/dismiss`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['alerts'] });
    },
  });
}
