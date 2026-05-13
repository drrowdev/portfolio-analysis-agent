import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';

export interface AnalysisSource {
  name: string;
  url: string;
  date: string;
}

export interface AnalysisInsight {
  title: string;
  detail: string;
  severity: 'info' | 'warning' | 'action';
  sources?: AnalysisSource[];
}

export interface AnalysisRecommendation {
  action: string;
  rationale: string;
  account_type: string;
  priority: 'high' | 'medium' | 'low';
}

export interface AnalysisContent {
  summary: string;
  insights: AnalysisInsight[];
  recommendations: AnalysisRecommendation[];
  risk_factors: string[];
}

export type AnalysisType = 'daily_summary' | 'rebalance' | 'tax_optimization' | 'news_impact';

export interface AnalysisHistoryItem {
  id: string;
  analysis_type: AnalysisType;
  content: AnalysisContent;
  created_at: string;
}

const ENDPOINT_MAP: Record<string, string> = {
  'daily-summary': '/analysis/daily-summary',
  'rebalance': '/analysis/rebalance',
  'tax-optimization': '/analysis/tax-optimization',
  'news-impact': '/analysis/news-impact',
};

export function useAnalysisHistory(limit = 20) {
  return useQuery<AnalysisHistoryItem[]>({
    queryKey: ['analysis', 'history', limit],
    queryFn: () => api.get(`/analysis/history?limit=${limit}`),
    staleTime: 60_000,
  });
}

export function useTriggerAnalysis() {
  const queryClient = useQueryClient();
  return useMutation<AnalysisContent, Error, string>({
    mutationFn: (analysisType) => {
      const endpoint = ENDPOINT_MAP[analysisType];
      if (!endpoint) throw new Error(`Unknown analysis type: ${analysisType}`);
      return api.post(endpoint, {});
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['analysis'] });
    },
  });
}
