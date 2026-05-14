import { useState } from 'react';
import { useAlerts, useMarkAlertRead, useDismissAlert } from '@/hooks/useAlerts';
import type { Alert } from '@/hooks/useAlerts';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Loader2, CheckCheck, X, Info, AlertTriangle, AlertCircle } from 'lucide-react';
import { cn } from '@/lib/utils';

const STATUS_TABS = [
  { label: 'All', value: '' },
  { label: 'New', value: 'new' },
  { label: 'Read', value: 'read' },
  { label: 'Dismissed', value: 'dismissed' },
] as const;

const ALERT_TYPE_LABELS: Record<string, string> = {
  price: 'Price',
  news: 'News',
  earnings: 'Earnings',
  recommendation: 'Recommendation',
  rebalance: 'Rebalance',
  tax: 'Tax',
};

function severityIcon(severity: Alert['severity']) {
  switch (severity) {
    case 'info':
      return <Info className="h-5 w-5 text-blue-500 shrink-0" />;
    case 'warning':
      return <AlertTriangle className="h-5 w-5 text-amber-500 shrink-0" />;
    case 'action':
      return <AlertCircle className="h-5 w-5 text-red-500 shrink-0" />;
  }
}

function severityBorder(severity: Alert['severity']) {
  switch (severity) {
    case 'info':
      return 'border-l-blue-500';
    case 'warning':
      return 'border-l-amber-500';
    case 'action':
      return 'border-l-red-500';
  }
}

function relativeTime(dateStr: string): string {
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMin = Math.floor(diffMs / 60_000);
  if (diffMin < 1) return 'just now';
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHours = Math.floor(diffMin / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  const diffDays = Math.floor(diffHours / 24);
  if (diffDays < 30) return `${diffDays}d ago`;
  return date.toLocaleDateString('fi-FI');
}

export function AlertsPage() {
  const [statusFilter, setStatusFilter] = useState('');
  const { data: alerts = [], isLoading } = useAlerts(statusFilter || undefined);
  const { data: newAlerts = [] } = useAlerts('new');
  const markRead = useMarkAlertRead();
  const dismiss = useDismissAlert();

  const newCount = newAlerts.length;

  const handleMarkAllRead = () => {
    const unread = alerts.filter((a) => a.status === 'new');
    unread.forEach((a) => markRead.mutate(a.id));
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-8 w-8 animate-spin text-emerald-500" />
        <span className="ml-3 text-muted-foreground">Loading alerts…</span>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h2 className="text-2xl font-bold text-foreground">Alerts</h2>
          <p className="text-sm text-muted-foreground">Stay on top of portfolio events and recommendations</p>
        </div>
        {newCount > 0 && (
          <Button
            variant="outline"
            size="sm"
            onClick={handleMarkAllRead}
            disabled={markRead.isPending}
          >
            <CheckCheck className="h-4 w-4 mr-1.5" />
            Mark all as read
          </Button>
        )}
      </div>

      {/* Tab Filters */}
      <div className="flex gap-1 rounded-lg bg-muted p-1 w-fit">
        {STATUS_TABS.map((tab) => (
          <button
            key={tab.value}
            onClick={() => setStatusFilter(tab.value)}
            className={cn(
              'relative rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
              statusFilter === tab.value
                ? 'bg-background text-foreground shadow-sm'
                : 'text-muted-foreground hover:text-foreground'
            )}
          >
            {tab.label}
            {tab.value === 'new' && newCount > 0 && (
              <Badge variant="destructive" className="ml-1.5 h-5 min-w-5 px-1 text-[10px]">
                {newCount}
              </Badge>
            )}
          </button>
        ))}
      </div>

      {/* Alert List */}
      {alerts.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-48 space-y-2">
          <span className="text-4xl">🎉</span>
          <p className="text-lg font-medium text-foreground">No alerts — you're all caught up!</p>
          <p className="text-sm text-muted-foreground">We'll notify you when something needs your attention.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {alerts.map((alert) => (
            <AlertCard
              key={alert.id}
              alert={alert}
              onMarkRead={() => markRead.mutate(alert.id)}
              onDismiss={() => dismiss.mutate(alert.id)}
              isMarkingRead={markRead.isPending}
              isDismissing={dismiss.isPending}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function AlertCard({
  alert,
  onMarkRead,
  onDismiss,
  isMarkingRead,
  isDismissing,
}: {
  alert: Alert;
  onMarkRead: () => void;
  onDismiss: () => void;
  isMarkingRead: boolean;
  isDismissing: boolean;
}) {
  return (
    <Card className={cn('border-l-4', severityBorder(alert.severity), alert.status === 'new' && 'bg-accent/30')}>
      <CardContent className="flex items-start gap-3 py-4">
        {severityIcon(alert.severity)}
        <div className="flex-1 min-w-0 space-y-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-semibold text-foreground">{alert.title}</span>
            <Badge variant="secondary" className="text-[10px] px-1.5">
              {ALERT_TYPE_LABELS[alert.alert_type] ?? alert.alert_type}
            </Badge>
            {alert.related_symbol && (
              <Badge variant="outline" className="text-[10px] px-1.5 font-mono">
                {alert.related_symbol}
              </Badge>
            )}
          </div>
          <p className="text-sm text-muted-foreground">{alert.message}</p>
          <span className="text-xs text-muted-foreground">{relativeTime(alert.created_at)}</span>
        </div>
        <div className="flex gap-1.5 shrink-0">
          {alert.status === 'new' && (
            <Button variant="ghost" size="sm" onClick={onMarkRead} disabled={isMarkingRead} title="Mark as read">
              <CheckCheck className="h-4 w-4" />
            </Button>
          )}
          {alert.status !== 'dismissed' && (
            <Button variant="ghost" size="sm" onClick={onDismiss} disabled={isDismissing} title="Dismiss">
              <X className="h-4 w-4" />
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
