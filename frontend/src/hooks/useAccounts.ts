import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { Account } from '@/types/portfolio';

export function useAccounts() {
  return useQuery<Account[]>({
    queryKey: ['accounts'],
    queryFn: () => api.get('/accounts/'),
    staleTime: 300_000,
  });
}
