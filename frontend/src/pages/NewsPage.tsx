import { useState, useMemo } from 'react';
import { useNews, useRefreshNews, useEarningsCalendar } from '@/hooks/useNews';
import { formatRelativeDate } from '@/lib/utils';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Newspaper, Loader2, RefreshCw, CalendarDays, ExternalLink } from 'lucide-react';

/** Convert YYYY-MM-DD to DD.MM.YYYY */
function formatDate(iso: string): string {
  const [y, m, d] = iso.split('-');
  return `${d}.${m}.${y}`;
}

function SentimentDot({ score }: { score: number | null }) {
  if (score === null) return <span className="inline-block h-2.5 w-2.5 rounded-full bg-gray-400" title="No sentiment" />;
  if (score > 0.2) return <span className="inline-block h-2.5 w-2.5 rounded-full bg-emerald-500" title={`Positive (${score.toFixed(2)})`} />;
  if (score < -0.2) return <span className="inline-block h-2.5 w-2.5 rounded-full bg-red-500" title={`Negative (${score.toFixed(2)})`} />;
  return <span className="inline-block h-2.5 w-2.5 rounded-full bg-gray-400" title={`Neutral (${score.toFixed(2)})`} />;
}

export function NewsPage() {
  const { data: articles = [], isLoading } = useNews();
  const refreshNews = useRefreshNews();
  const { data: earnings = [] } = useEarningsCalendar();

  const [symbolFilter, setSymbolFilter] = useState('all');
  const [sourceFilter, setSourceFilter] = useState('all');

  const uniqueSymbols = useMemo(
    () => [...new Set(articles.map((a) => a.symbol).filter(Boolean))] as string[],
    [articles],
  );
  const uniqueSources = useMemo(
    () => [...new Set(articles.map((a) => a.source).filter(Boolean))],
    [articles],
  );

  const filtered = useMemo(
    () =>
      articles.filter((a) => {
        const matchSymbol = symbolFilter === 'all' || a.symbol === symbolFilter;
        const matchSource = sourceFilter === 'all' || a.source === sourceFilter;
        return matchSymbol && matchSource;
      }),
    [articles, symbolFilter, sourceFilter],
  );

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-8 w-8 animate-spin text-emerald-500" />
        <span className="ml-3 text-muted-foreground">Loading news…</span>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h2 className="text-2xl font-bold text-foreground">Market News</h2>
        <p className="text-sm text-muted-foreground">News relevant to your portfolio holdings</p>
      </div>

      {/* Filter bar */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex gap-2">
          <Select value={symbolFilter} onValueChange={setSymbolFilter}>
            <SelectTrigger className="w-[140px] sm:w-[160px]">
              <SelectValue placeholder="All symbols" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All symbols</SelectItem>
              {uniqueSymbols.map((s) => (
                <SelectItem key={s} value={s}>{s}</SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Select value={sourceFilter} onValueChange={setSourceFilter}>
            <SelectTrigger className="w-[140px] sm:w-[180px]">
              <SelectValue placeholder="All sources" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All sources</SelectItem>
              {uniqueSources.map((s) => (
                <SelectItem key={s} value={s}>{s}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <Button
          variant="outline"
          size="sm"
          onClick={() => refreshNews.mutate()}
          disabled={refreshNews.isPending}
        >
          <RefreshCw className={`h-4 w-4 mr-2 ${refreshNews.isPending ? 'animate-spin' : ''}`} />
          {refreshNews.isPending ? 'Refreshing…' : 'Refresh News'}
        </Button>
      </div>

      {/* Two-column layout: News + Earnings sidebar */}
      <div className="flex flex-col lg:flex-row gap-6">
        {/* Earnings sidebar — on top for mobile, sticky sidebar on large screens */}
        {earnings.length > 0 && (
          <div className="lg:order-2 lg:w-72 lg:shrink-0">
            <div className="lg:sticky lg:top-6 space-y-3">
              <h3 className="text-lg font-semibold text-foreground flex items-center gap-2">
                <CalendarDays className="h-5 w-5" />
                Upcoming Earnings
              </h3>
              <div className="grid gap-3 grid-cols-2 lg:grid-cols-1">
                {earnings.map((e, i) => (
                  <Card key={`${e.symbol}-${e.date}-${i}`}>
                    <CardContent className="pt-4">
                      <div className="flex items-center justify-between mb-1">
                        <Badge variant="outline" className="font-mono">{e.symbol}</Badge>
                        {e.date && (
                          <span className="text-xs text-muted-foreground">{formatDate(e.date)}</span>
                        )}
                      </div>
                      {e.quarter != null && e.year != null && (
                        <p className="text-sm text-muted-foreground">Q{e.quarter} {e.year}</p>
                      )}
                      {e.estimate_eps != null && (
                        <p className="text-xs text-muted-foreground">
                          EPS est: {e.estimate_eps.toFixed(2)}
                          {e.actual_eps != null && ` · actual: ${e.actual_eps.toFixed(2)}`}
                        </p>
                      )}
                    </CardContent>
                  </Card>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* News articles — takes remaining width */}
        <div className="flex-1 min-w-0 lg:order-1">
          {filtered.length > 0 ? (
            <div className="space-y-4">
              {filtered.map((article) => (
                <Card key={article.id} className="hover:border-emerald-500/30 transition-colors">
                  <CardHeader className="pb-2">
                    <div className="flex items-start justify-between gap-4">
                      <div className="flex items-start gap-2 min-w-0">
                        <Newspaper className="h-4 w-4 mt-0.5 shrink-0 text-muted-foreground" />
                        <a
                          href={article.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-base font-semibold hover:text-emerald-500 transition-colors leading-snug"
                        >
                          {article.title}
                          <ExternalLink className="inline ml-1.5 h-3 w-3 opacity-50" />
                        </a>
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        <SentimentDot score={article.sentiment_score} />
                        {article.published_at && (
                          <span className="text-xs text-muted-foreground whitespace-nowrap">
                            {formatRelativeDate(article.published_at)}
                          </span>
                        )}
                      </div>
                    </div>
                  </CardHeader>
                  <CardContent>
                    {article.summary && (
                      <p className="text-sm text-muted-foreground line-clamp-3">{article.summary}</p>
                    )}
                    <div className="mt-3 flex items-center gap-2">
                      <Badge variant="secondary">{article.source}</Badge>
                      {article.symbol && (
                        <Badge variant="outline">{article.symbol}</Badge>
                      )}
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          ) : (
            <Card>
              <CardContent className="flex flex-col items-center justify-center py-16 text-center">
                <Newspaper className="h-12 w-12 text-muted-foreground/40 mb-4" />
                <p className="text-muted-foreground mb-4">No news articles yet</p>
                <Button
                  variant="outline"
                  onClick={() => refreshNews.mutate()}
                  disabled={refreshNews.isPending}
                >
                  <RefreshCw className={`h-4 w-4 mr-2 ${refreshNews.isPending ? 'animate-spin' : ''}`} />
                  Refresh News
                </Button>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
