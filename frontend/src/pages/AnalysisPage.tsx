import { useState } from 'react';
import {
  useAnalysisHistory,
  useGuidance,
  useRefreshGuidance,
  useTriggerAnalysis,
} from '@/hooks/useAnalysis';
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
  Gauge,
  RefreshCw,
  Sparkles,
  SlidersHorizontal,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { ProofOfValueCard } from '@/components/analysis/ProofOfValueCard';
import { ConsumerGuidance } from '@/components/analysis/ConsumerGuidance';
import { toast } from '@/hooks/useToast';

const ANALYSIS_TYPES = [
  {
    key: 'daily-summary',
    label: 'Market Research',
    icon: Newspaper,
    emoji: '🗞️',
    description: 'Summarize current portfolio news with sources',
    historyType: 'daily_summary',
  },
  {
    key: 'rebalance',
    label: 'Risk Review',
    icon: Scale,
    emoji: '⚖️',
    description: 'Audit concentration and risk limits without generating a trade',
    historyType: 'rebalance',
  },
  {
    key: 'tax-optimization',
    label: 'Tax Optimization',
    icon: Landmark,
    emoji: '🏛️',
    description: 'Review tax-data readiness and bracket facts without sale advice',
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
  rebalance: 'Risk Review',
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
  const guidanceQuery = useGuidance();
  const refreshGuidance = useRefreshGuidance();
  const trigger = useTriggerAnalysis();
  const [runningType, setRunningType] = useState<string | null>(null);
  const [latestResult, setLatestResult] = useState<
    Record<string, { content: AnalysisContent; created_at: string }>
  >({});
  const [expandedHistory, setExpandedHistory] = useState<Set<string>>(new Set());

  const handleRunAnalysis = async (typeKey: string) => {
    setRunningType(typeKey);
    try {
      const result = await trigger.mutateAsync(typeKey);
      setLatestResult((previous) => ({
        ...previous,
        [typeKey]: { content: result, created_at: new Date().toISOString() },
      }));
    } catch (error) {
      toast({
        title: 'Optional analysis failed',
        description: error instanceof Error ? error.message : 'The analysis could not be completed.',
        variant: 'destructive',
      });
    } finally {
      setRunningType(null);
    }
  };

  const handleRefreshGuidance = async () => {
    try {
      const result = await refreshGuidance.mutateAsync();
      const blocked = result.steps.find((step) => step.status === 'blocked');
      toast({
        title: blocked ? 'Portfolio refreshed with blockers' : 'Portfolio refreshed',
        description: blocked?.detail ?? 'Prices and portfolio checks are current.',
      });
    } catch (error) {
      toast({
        title: 'Portfolio refresh failed',
        description: error instanceof Error ? error.message : 'The refresh could not be completed.',
        variant: 'destructive',
      });
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
      latestByType[at.historyType] = latestResult[at.key];
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <Gauge className="h-6 w-6 text-emerald-500" />
            <h2 className="text-2xl font-bold text-foreground">Portfolio Cockpit</h2>
          </div>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            Portfolio risk, benchmark performance, and tracked tax and cost facts.
          </p>
        </div>
        <div className="flex min-w-56 flex-col gap-2 sm:items-end">
          <Button
            onClick={handleRefreshGuidance}
            disabled={runningType !== null || refreshGuidance.isPending}
            className="bg-emerald-600 hover:bg-emerald-700"
          >
            <RefreshCw
              className={cn('mr-2 h-4 w-4', refreshGuidance.isPending && 'animate-spin')}
            />
            {refreshGuidance.isPending ? 'Refreshing portfolio...' : 'Refresh portfolio'}
          </Button>
          {refreshGuidance.data && (
            <p role="status" aria-live="polite" className="max-w-sm text-xs text-muted-foreground sm:text-right">
              Checked {formatTimestamp(refreshGuidance.data.guidance.as_of)} ·{' '}
              {refreshGuidance.data.steps[0]?.detail}
            </p>
          )}
        </div>
      </div>

      <ConsumerGuidance
        guidance={guidanceQuery.data}
        loading={guidanceQuery.isLoading}
        error={guidanceQuery.error}
      />

      <NewsResearchCard
        entry={latestByType.daily_summary}
        isRunning={runningType === 'daily-summary'}
        disabled={runningType !== null || refreshGuidance.isPending}
        onRun={() => handleRunAnalysis('daily-summary')}
      />

      <details className="group rounded-lg border border-border bg-card">
        <summary className="flex cursor-pointer list-none items-center gap-3 px-4 py-4 hover:bg-accent/20">
          <SlidersHorizontal className="h-4 w-4 text-muted-foreground" />
          <div className="flex-1">
            <p className="text-sm font-medium text-foreground">Advanced evidence and tools</p>
            <p className="text-xs text-muted-foreground">
              Optional model output, backtests, assumptions, and history
            </p>
          </div>
          <Badge variant="outline">Optional</Badge>
          <ChevronRight className="h-4 w-4 text-muted-foreground transition-transform group-open:rotate-90" />
        </summary>

        <div className="space-y-6 border-t border-border p-4">
          <div>
            <h3 className="text-sm font-semibold text-foreground">Run an optional specialist analysis</h3>
            <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {ANALYSIS_TYPES.map((analysisType) => {
                const Icon = analysisType.icon;
                const isRunning = runningType === analysisType.key;
                return (
                  <Card key={analysisType.key} className="flex flex-col">
                    <CardContent className="flex flex-1 flex-col p-4">
                      <div className="flex items-center gap-2">
                        <Icon className="h-4 w-4 text-emerald-500" />
                        <p className="text-sm font-medium">{analysisType.label}</p>
                      </div>
                      <p className="mb-3 mt-2 flex-1 text-xs text-muted-foreground">
                        {analysisType.description}
                      </p>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => handleRunAnalysis(analysisType.key)}
                        disabled={runningType !== null || refreshGuidance.isPending}
                      >
                        {isRunning && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
                        Run check
                      </Button>
                    </CardContent>
                  </Card>
                );
              })}
            </div>
          </div>

          {Object.keys(latestByType).length > 0 && (
            <div className="space-y-4">
              <h3 className="text-sm font-semibold text-foreground">Full latest analyses</h3>
              {ANALYSIS_TYPES.map((analysisType) => {
                const entry = latestByType[analysisType.historyType];
                if (!entry) return null;
                return (
                  <AnalysisResultCard
                    key={analysisType.key}
                    label={analysisType.label}
                    emoji={analysisType.emoji}
                    content={entry.content}
                    createdAt={entry.created_at}
                  />
                );
              })}
            </div>
          )}

          <ProofOfValueCard />

          <div className="space-y-3">
            <h3 className="text-sm font-semibold text-foreground">Analysis history</h3>
            {historyLoading ? (
              <div className="flex items-center gap-2 text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                Loading history…
              </div>
            ) : history.length === 0 ? (
              <p className="text-sm text-muted-foreground">No analysis history yet.</p>
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
      </details>
    </div>
  );
}

function NewsResearchCard({
  entry,
  isRunning,
  disabled,
  onRun,
}: {
  entry?: { content: AnalysisContent; created_at: string };
  isRunning: boolean;
  disabled: boolean;
  onRun: () => void;
}) {
  const unavailable = entry?.content.summary.startsWith('Analysis unavailable');

  return (
    <Card className="border-violet-500/20">
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-violet-500" />
              <CardTitle className="text-base">News research</CardTitle>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              Summarize recent portfolio news with sources.
            </p>
          </div>
          <Button size="sm" variant="outline" onClick={onRun} disabled={disabled}>
            {isRunning && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
            {isRunning ? 'Analyzing news...' : 'Analyze news'}
          </Button>
        </div>
      </CardHeader>
      {entry && (
        <CardContent className="space-y-3">
          <div
            className={cn(
              'rounded-md border p-3 text-sm',
              unavailable
                ? 'border-amber-500/30 bg-amber-500/5 text-muted-foreground'
                : 'border-border bg-accent/30 text-foreground',
            )}
          >
            {entry.content.summary}
          </div>
          {entry.content.insights.length > 0 && (
            <div className="grid gap-2 md:grid-cols-2">
              {entry.content.insights.slice(0, 4).map((insight) => (
                <div key={`${insight.title}-${insight.detail}`} className="rounded-md border border-border p-3">
                  <p className="text-sm font-medium text-foreground">{insight.title}</p>
                  <p className="mt-1 text-xs text-muted-foreground">{insight.detail}</p>
                  {(insight.sources?.length ?? 0) > 0 && (
                    <div className="mt-2 flex flex-wrap gap-2">
                      {insight.sources!.map((source) => (
                        <a
                          key={`${source.url}-${source.date}`}
                          href={source.url}
                          target="_blank"
                          rel="noreferrer"
                          className="text-[10px] text-emerald-500 hover:underline"
                        >
                          {source.name} · {source.date}
                        </a>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
          <p className="text-[11px] text-muted-foreground">
            Updated {formatTimestamp(entry.created_at)}
          </p>
        </CardContent>
      )}
    </Card>
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
      {content.meta?.mode === 'shadow' && (
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <Badge variant="secondary">Shadow mode</Badge>
          <span>Prompt {content.meta.prompt_version}</span>
          {!content.meta.can_recommend_trades && (
            <Badge variant="warning">Trade decisions blocked</Badge>
          )}
        </div>
      )}

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
              {(insight.sources?.length ?? 0) > 0 && (
                <div className="mt-2 flex flex-wrap gap-2">
                  {insight.sources!.map((source) => (
                    <a
                      key={`${source.url}-${source.date}`}
                      href={source.url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-[10px] text-emerald-500 hover:underline"
                    >
                      {source.name} · {source.date}
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
          <h4 className="text-sm font-medium text-foreground">Shadow decisions</h4>
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
                  {rec.decision && (
                    <Badge variant="secondary" className="text-[10px] px-1.5">
                      {rec.decision}
                    </Badge>
                  )}
                  {rec.candidate_objective === 'risk_enforcement' && (
                    <Badge variant="outline" className="text-[10px] px-1.5">
                      risk-limit review
                    </Badge>
                  )}
                  {rec.confidence && (
                    <span className="text-[10px] text-muted-foreground">
                      {rec.confidence} confidence
                      {rec.urgency && rec.urgency !== 'none' ? ` · ${rec.urgency}` : ''}
                    </span>
                  )}
                </div>
                <p className="text-xs text-muted-foreground">{rec.rationale}</p>
                {rec.candidate_objective === 'risk_enforcement' && (
                  <div className="space-y-1 rounded-md bg-muted/40 p-2 text-xs text-muted-foreground">
                    <p>
                      Shadow amount €{Number(rec.amount_eur ?? 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}
                      {' · '}quantity {Number(rec.quantity ?? 0).toLocaleString(undefined, { maximumFractionDigits: 6 })}
                      {' · '}reference €{Number(rec.reference_price_eur ?? 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}
                    </p>
                    <p>
                      Estimated cost €{Number(rec.estimated_transaction_cost_eur ?? 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}
                      {' · '}estimated tax €{Number(rec.estimated_tax_impact_eur ?? 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}
                      {rec.valid_until ? ` · expires ${new Date(rec.valid_until).toLocaleDateString()}` : ''}
                    </p>
                    {rec.risk_impact && <p>{rec.risk_impact}</p>}
                    <p>No return, downside, or alpha forecast is attached to this risk-only candidate.</p>
                  </div>
                )}
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
