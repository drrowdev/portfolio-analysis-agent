import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';

export interface GoalRead {
  id: string;
  name: string;
  target_amount_eur: number;
  target_date: string;           // YYYY-MM-DD
  assumed_annual_return_pct: number;
  notes: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface GoalProjection {
  goal: GoalRead;
  current_value_eur: number;
  progress_pct: number;
  gap_eur: number;
  months_remaining: number;
  projected_value_no_contributions: number;
  shortfall_no_contributions: number;
  required_monthly_eur: number;
}

export interface GoalCreatePayload {
  name: string;
  target_amount_eur: number;
  target_date: string;
  assumed_annual_return_pct?: number;
  notes?: string;
}

export interface GoalUpdatePayload {
  name?: string;
  target_amount_eur?: number;
  target_date?: string;
  assumed_annual_return_pct?: number;
  notes?: string;
  is_active?: boolean;
}

export function useGoals() {
  return useQuery<GoalProjection[]>({
    queryKey: ['goals'],
    queryFn: () => api.get('/goals/'),
    staleTime: 60_000,
  });
}

export function useCreateGoal() {
  const qc = useQueryClient();
  return useMutation<GoalProjection, Error, GoalCreatePayload>({
    mutationFn: (data) => api.post('/goals/', data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['goals'] }),
  });
}

export function useUpdateGoal() {
  const qc = useQueryClient();
  return useMutation<GoalProjection, Error, { id: string; data: GoalUpdatePayload }>({
    mutationFn: ({ id, data }) => api.patch(`/goals/${id}`, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['goals'] }),
  });
}

export function useDeleteGoal() {
  const qc = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: (id) => api.delete(`/goals/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['goals'] }),
  });
}
