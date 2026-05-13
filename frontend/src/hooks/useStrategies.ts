import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { Strategy, StrategyCreate, StrategyUpdate } from '@/types/strategy';

export function useStrategies() {
  return useQuery<Strategy[]>({
    queryKey: ['strategies'],
    queryFn: () => api.get('/strategies/'),
    staleTime: 300_000,
  });
}

export function useActiveStrategy() {
  return useQuery<Strategy | null>({
    queryKey: ['strategies', 'active'],
    queryFn: async () => {
      const strategies = await api.get<Strategy[]>('/strategies/');
      return strategies.find((s) => s.is_active) ?? null;
    },
    staleTime: 300_000,
  });
}

export function useCreateStrategy() {
  const queryClient = useQueryClient();
  return useMutation<Strategy, Error, StrategyCreate>({
    mutationFn: (data) => api.post<Strategy>('/strategies/', data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['strategies'] });
    },
  });
}

export function useUpdateStrategy() {
  const queryClient = useQueryClient();
  return useMutation<Strategy, Error, { id: string; data: StrategyUpdate }>({
    mutationFn: ({ id, data }) => api.patch<Strategy>(`/strategies/${id}`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['strategies'] });
    },
  });
}
