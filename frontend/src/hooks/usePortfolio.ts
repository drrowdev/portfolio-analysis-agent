import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { PortfolioSummary, Holding, UploadResponse } from '@/types/portfolio';

export function usePortfolioSummary() {
  return useQuery<PortfolioSummary>({
    queryKey: ['portfolio', 'summary'],
    queryFn: () => api.get('/portfolio/summary'),
    staleTime: 5 * 60_000, // 5 min — prices refresh every 5-15 min on backend
    retry: false,
  });
}

export function useHoldings() {
  return useQuery<Holding[]>({
    queryKey: ['holdings'],
    queryFn: () => api.get('/holdings/'),
    staleTime: 5 * 60_000,
  });
}

export function useUploadNordnet() {
  const queryClient = useQueryClient();
  return useMutation<UploadResponse, Error, { file: File; accountType: 'arvo_osuustili' | 'osakesaastotili' }>({
    mutationFn: ({ file, accountType }) =>
      api.uploadNordnet<UploadResponse>(file, accountType),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['portfolio'] });
      queryClient.invalidateQueries({ queryKey: ['holdings'] });
      queryClient.invalidateQueries({ queryKey: ['accounts'] });
    },
  });
}

export function useUploadFidelity() {
  const queryClient = useQueryClient();
  return useMutation<UploadResponse, Error, { file: File }>({
    mutationFn: ({ file }) =>
      api.uploadFidelity<UploadResponse>(file),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['portfolio'] });
      queryClient.invalidateQueries({ queryKey: ['holdings'] });
      queryClient.invalidateQueries({ queryKey: ['accounts'] });
    },
  });
}
