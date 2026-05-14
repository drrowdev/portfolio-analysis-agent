import { useState } from 'react';
import { useAnalysisHistory, useTriggerAnalysis } from '@/hooks/useAnalysis';
import type { AnalysisContent, AnalysisHistoryItem } from '@/hooks/useAnalysis';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Loader2,
  Scale,
  Landmark,
  Newspaper,
  ChevronDown,
  ChevronRight,
  Clock,
  Sparkles,
} from 'lucide-react';
import { cn } from '@/lib/utils';

const ANALYSIS_TYPES = [
  {
    key: 'rebalance',
    label: 'Rebalance',
    icon: Scale,
    emoji: '⚖️',
    description: 'Check if your portfolio needs rebalancing based on your strategy',
    historyType: 'rebalance',
  },
  {
    key: 'tax-optimization',
    label: 'Tax Optimization',
    icon: Landmark,
    emoji: '🏛️',
    description: 'Find tax-saving opportunities across AOT, OST, and ESPP accounts',
    historyType: 'tax_optimization',
  },
  {
    key: 'news-impact',
    label: 'News Impact',
    icon: Newspaper,
    emoji: '📰',
    description: 'Analyze how recent news affects your holdings',
    historyType: 'news_impact',
  },
] as const;

const TYPE_LABELS: Record<string, string> = {
  daily_summary: 'Daily Summary',
  rebalance: 'Rebalance',
  tax_optimization: 'Tax Optimization',
  news_impact: 'News Impact',
};

function formatTimestamp(dateStr: string): string {
  const date = new Date(dateStr);
  return date.toLocaleString('fi-FI', {
    month: 'numeric',
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

export function AnalysisPage() {
  const { data: history = [], isLoading: historyLoading } = useAnalysisHistory();
  const trigger = useTriggerAnalysis();
  const [runningType, setRunningType] = useState<string | null>(null);
  const [latestResult, setLatestResult] = useState<Record<string, AnalysisContent>>({});
  const [expandedHistory, setExpandedHistory] = useState<Set<string>>(new Set());

  const handleRunAnalysis = async (typeKey: string) => {
    setRunningType(typeKey);
    try {
      const result = await trigger.mutateAsync(typeKey);
      setLatestResult((prev) => ({ ...prev, [typeKey]: result }));
    } catch {
      // Error handled by React Query
    } finally {
      setRunningType(null);
    }
  };

  const toggleHistory = (id: string) => {
    setExpandedHistory((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  // Build latest results: merge local trigger results with history
  const latestByType: Record<string, { content: AnalysisContent; created_at: string }> = {};
  for (const item of history) {
    if (!latestByType[item.analysis_type]) {
      latestByType[item.analysis_type] = { content: item.content, created_at: item.created_at };
    }
  }
  // Override with freshly-triggered results
  for (const at of ANALYSIS_TYPES) {
    if (latestResult[at.key]) {
      latestByType[at.historyType] = { content: latestResult[at.key], created_at: new Date().toISOString() };
    }
  }

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2">
          <Sparkles className="h-6 w-6 text-emerald-500" />
          <h2 className="text-2xl font-bold text-foreground">AI Analysis</h2>
        </div>
        <p className="text-sm text-muted-foreground mt-1">Claude-powered portfolio insights</p>
      </div>

      {/* Action Cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {ANALYSIS_TYPES.map((at) => {
          const isRunning = runningType === at.key;
          return (
            <Card key={at.key} className="flex flex-col">
              <CardHeader className="pb-2">
                <div className="flex items-center gap-2">
                  <span className="text-xl">{at.emoji}</span>
                  <CardTitle className="text-sm font-semibold">{at.label}</CardTitle>
                </div>
              </CardHeader>
              <CardContent className="flex flex-col flex-1">
                <p className="text-xs text-muted-foreground flex-1 mb-4">{at.description}</p>
                <Button
                  size="sm"
                  className="w-full bg-emerald-600 hover:bg-emerald-700"
                  onClick={() => handleRunAnalysis(at.key)}
                  disabled={isRunning}
                >
                  {isRunning ? (
                    <>
                      <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />
                      Analyzing…
                    </>
                  ) : (
                    'Run Analysis'
                  )}
                </Button>
              </CardContent>
            </Card>
          );
        })}
      </div>

      {/* Latest Results */}
      {Object.keys(latestByType).length > 0 && (
        <div className="space-y-6">
          <h3 className="text-lg font-semibold text-foreground">Latest Results</h3>
          {ANALYSIS_TYPES.map((at) => {
            const entry = latestByType[at.historyType];
            if (!entry) return null;
            return (
              <AnalysisResultCard
                key={at.key}
                label={at.label}
                emoji={at.emoji}
                content={entry.content}
                createdAt={entry.created_at}
              />
            );
          })}
        </div>
      )}

      {/* History */}
      <div className="space-y-4">
        <h3 className="text-lg font-semibold text-foreground">History</h3>
        {historyLoading ? (
          <div className="flex items-center gap-2 text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading history…
          </div>
        ) : history.length === 0 ? (
          <p className="text-sm text-muted-foreground">No analysis history yet. Run your first analysis above!</p>
        ) : (
          <div className="space-y-2">
            {history.map((item) => (
              <HistoryItem
                key={item.id}
                item={item}
                expanded={expandedHistory.has(item.id)}
                onToggle={() => toggleHistory(item.id)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function AnalysisResultCard({
  label,
  emoji,
  content,
  createdAt,
}: {
  label: string;
  emoji: string;
  content: AnalysisContent;
  createdAt: string;
}) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span>{emoji}</span>
            <CardTitle className="text-base">{label}</CardTitle>
          </div>
          <span className="text-xs text-muted-foreground flex items-center gap-1">
            <Clock className="h-3 w-3" />
            {formatTimestamp(createdAt)}
          </span>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <AnalysisContentRenderer content={content} />
      </CardContent>
    </Card>
  );
}

function AnalysisContentRenderer({ content }: { content: AnalysisContent }) {
  return (
    <>
      {/* Summary */}
      {content.summary && (
        <p className="text-sm text-foreground bg-accent/50 rounded-md p-3">{content.summary}</p>
      )}

      {/* Insights */}
      {content.insights?.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-sm font-medium text-foreground">Insights</h4>
          {content.insights.map((insight, i) => (
            <div key={i} className={cn('border-l-4 rounded-md p-3 bg-accent/30', severityColor(insight.severity))}>
              <p className="text-sm font-medium text-foreground">{insight.title}</p>
              <p className="text-xs text-muted-foreground mt-1">{insight.detail}</p>
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
                  <Badge variant={priorityBadgeVariant(rec.priority)} className="text-[10px] px-1.5">
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
              <li key={i} className="text-xs text-muted-foreground">{risk}</li>
            ))}
          </ul>
        </div>
      )}
    </>
  );
}

function HistoryItem({
  item,
  expanded,
  onToggle,
}: {
  item: AnalysisHistoryItem;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <Card>
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-accent/30 transition-colors rounded-lg"
      >
        {expanded ? (
          <ChevronDown className="h-4 w-4 text-muted-foreground shrink-0" />
        ) : (
          <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0" />
        )}
        <Badge variant="secondary" className="text-[10px]">
          {TYPE_LABELS[item.analysis_type] ?? item.analysis_type}
        </Badge>
        <span className="text-xs text-muted-foreground flex items-center gap-1 ml-auto">
          <Clock className="h-3 w-3" />
          {formatTimestamp(item.created_at)}
        </span>
      </button>
      {expanded && (
        <CardContent className="pt-0 pb-4 space-y-4">
          <AnalysisContentRenderer content={item.content} />
        </CardContent>
      )}
    </Card>
  );
}
