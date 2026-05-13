import { useQuery } from '@tanstack/react-query';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { api } from '@/lib/api';
import { CalendarDays } from 'lucide-react';

interface EarningsEvent {
  symbol: string;
  date: string;
  event: string;
}

interface EarningsData {
  events: EarningsEvent[];
}

function formatDate(dateStr: string): string {
  const d = new Date(dateStr + 'T00:00:00');
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
}

function daysUntil(dateStr: string): number {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const target = new Date(dateStr + 'T00:00:00');
  return Math.ceil((target.getTime() - today.getTime()) / (1000 * 60 * 60 * 24));
}

export function EarningsCalendar() {
  const { data, isLoading } = useQuery({
    queryKey: ['earnings-calendar'],
    queryFn: () => api.get<EarningsData>('/portfolio/earnings-calendar'),
    staleTime: 24 * 60 * 60 * 1000, // 24 hours — backend caches for 24h
    gcTime: 24 * 60 * 60 * 1000,
  });

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium">Upcoming Earnings</CardTitle>
        </CardHeader>
        <CardContent>
          <Skeleton className="h-[100px] w-full" />
        </CardContent>
      </Card>
    );
  }

  if (!data || data.events.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium">Upcoming Earnings</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground text-center py-4">No upcoming earnings in the next 90 days</p>
        </CardContent>
      </Card>
    );
  }

  // Filter out past events (backend cache may serve stale dates)
  const futureEvents = data.events.filter(e => daysUntil(e.date) >= 0);

  if (futureEvents.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium">Upcoming Earnings</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground text-center py-4">No upcoming earnings in the next 90 days</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium flex items-center gap-2">
          <CalendarDays className="h-4 w-4" />
          Upcoming Earnings
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-3">
          {futureEvents.map((e, i) => {
            const days = daysUntil(e.date);
            const isImminent = days <= 7;
            const isSoon = days <= 14;
            return (
              <div key={`${e.symbol}-${i}`} className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className={`w-2 h-2 rounded-full ${isImminent ? 'bg-red-500' : isSoon ? 'bg-amber-500' : 'bg-slate-400'}`} />
                  <div>
                    <span className="text-sm font-medium">{e.symbol}</span>
                    <span className="text-xs text-muted-foreground ml-2">{e.event}</span>
                  </div>
                </div>
                <div className="text-right">
                  <p className="text-sm tabular-nums">{formatDate(e.date)}</p>
                  <p className={`text-xs ${isImminent ? 'text-red-500 font-medium' : 'text-muted-foreground'}`}>
                    {days === 0 ? 'Today' : days === 1 ? 'Tomorrow' : `in ${days}d`}
                  </p>
                </div>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}
