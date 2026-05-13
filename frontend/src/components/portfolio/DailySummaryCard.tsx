import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { AnalysisHistoryItem, AnalysisSource } from '@/hooks/useAnalysis';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { RefreshCw, Loader2, Clock, BarChart3, ExternalLink, ChevronDown, ChevronUp } from 'lucide-react';
import { cn } from '@/lib/utils';

function formatTimestamp(dateStr: string): string {
  const date = new Date(dateStr);
  return date.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function severityColor(severity: string) {
  switch (severity) {
    case 'info':
      return 'border-l-blue-500';
    case 'warning':
      return 'border-l-amber-500';
    case 'action':
      return 'border-l-red-500';
    default:
      return 'border-l-border';
  }
}

function priorityBadgeVariant(priority: string): 'destructive' | 'warning' | 'success' {
  switch (priority) {
    case 'high':
      return 'destructive';
    case 'medium':
      return 'warning';
    default:
      return 'success';
  }
}

export function DailySummaryCard() {
  const [isCollapsed, setIsCollapsed] = useState(false);
  const { data: latest, isLoading } = useQuery<AnalysisHistoryItem | null>({
    queryKey: ['analysis', 'latest-daily-summary'],
    queryFn: () => api.fetchLatestDailySummary(),
    staleTime: Infinity, // Only refreshes on manual "Generate" click
  });

  const queryClient = useQueryClient();
  const runMutation = useMutation({
    mutationFn: () => api.triggerDailySummary(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['analysis'] });
    },
  });

  const content = latest?.content;
  const isRunning = runMutation.isPending;

  if (isLoading) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-8">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          <span className="ml-2 text-sm text-muted-foreground">Loading summary…</span>
        </CardContent>
      </Card>
    );
  }

  if (!content) {
    return (
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <span className="text-xl">📊</span>
            <CardTitle className="text-sm font-medium">Daily Summary</CardTitle>
          </div>
        </CardHeader>
        <CardContent className="flex flex-col items-center gap-3 py-4">
          <BarChart3 className="h-8 w-8 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">No daily summary yet</p>
          <Button
            size="sm"
            className="bg-emerald-600 hover:bg-emerald-700"
            onClick={() => runMutation.mutate()}
            disabled={isRunning}
          >
            {isRunning ? (
              <>
                <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />
                Generating…
              </>
            ) : (
              'Generate Summary'
            )}
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <button
            onClick={() => setIsCollapsed(!isCollapsed)}
            className="flex items-center gap-2 hover:opacity-80 transition-opacity"
          >
            <span className="text-xl">📊</span>
            <CardTitle className="text-sm font-medium">Daily Summary</CardTitle>
            {isCollapsed ? (
              <ChevronDown className="h-4 w-4 text-muted-foreground" />
            ) : (
              <ChevronUp className="h-4 w-4 text-muted-foreground" />
            )}
          </button>
          <div className="flex items-center gap-2">
            {latest?.created_at && (
              <span className="text-xs text-muted-foreground flex items-center gap-1">
                <Clock className="h-3 w-3" />
                {formatTimestamp(latest.created_at)}
              </span>
            )}
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              onClick={() => runMutation.mutate()}
              disabled={isRunning}
            >
              {isRunning ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <RefreshCw className="h-4 w-4" />
              )}
            </Button>
          </div>
        </div>
      </CardHeader>
      {!isCollapsed && (
      <CardContent className="space-y-4">
        {/* Summary */}
        {content.summary && (
          <p className="text-sm text-foreground bg-accent/50 rounded-md p-3">{content.summary}</p>
        )}

        {/* Insights */}
        {content.insights?.length > 0 && (
          <div className="space-y-2">
            <h4 className="text-sm font-medium text-foreground">Insights</h4>
            {content.insights.map((insight, i) => (
              <div
                key={i}
                className={cn(
                  'border-l-4 rounded-md p-3 bg-accent/30',
                  severityColor(insight.severity),
                )}
              >
                <p className="text-sm font-medium text-foreground">{insight.title}</p>
                <p className="text-xs text-muted-foreground mt-1">{insight.detail}</p>
                {(insight.sources?.length ?? 0) > 0 && (
                  <div className="flex flex-wrap gap-x-3 gap-y-1 mt-2">
                    {insight.sources!.map((src: AnalysisSource, j: number) => (
                      <a
                        key={j}
                        href={src.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-[11px] text-primary hover:text-primary/80 hover:underline transition-colors"
                        title={src.name}
                      >
                        <ExternalLink className="h-3 w-3 shrink-0" />
                        <span className="truncate max-w-[180px]">{src.name}</span>
                        <span className="text-muted-foreground">({src.date})</span>
                      </a>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Recommendations */}
        {content.recommendations?.length > 0 && (
          <div className="space-y-2">
            <h4 className="text-sm font-medium text-foreground">Recommendations</h4>
            {content.recommendations.map((rec, i) => (
              <div key={i} className="flex items-start gap-3 rounded-md border border-border p-3">
                <div className="flex-1 min-w-0 space-y-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-medium text-foreground">{rec.action}</span>
                    <Badge
                      variant={priorityBadgeVariant(rec.priority)}
                      className="text-[10px] px-1.5"
                    >
                      {rec.priority}
                    </Badge>
                    {rec.account_type && (
                      <Badge variant="outline" className="text-[10px] px-1.5">
                        {rec.account_type}
                      </Badge>
                    )}
                  </div>
                  <p className="text-xs text-muted-foreground">{rec.rationale}</p>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Risk Factors */}
        {content.risk_factors?.length > 0 && (
          <div className="space-y-1">
            <h4 className="text-sm font-medium text-foreground">Risk Factors</h4>
            <ul className="list-disc list-inside space-y-1">
              {content.risk_factors.map((risk, i) => (
                <li key={i} className="text-xs text-muted-foreground">
                  {risk}
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
      )}
    </Card>
  );
}
