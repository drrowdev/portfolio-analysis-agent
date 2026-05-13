import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query';
import { RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { api } from '@/lib/api';
import type { MarketStatusResponse, ExchangeStatus } from '@/lib/api';

function ExchangeIndicator({ exchange }: { exchange: ExchangeStatus }) {
  const isOpen = exchange.status === 'open';
  return (
    <div className="flex items-center gap-2">
      <span
        className={`inline-block h-2.5 w-2.5 rounded-full ${isOpen ? 'bg-emerald-500' : 'bg-red-500'}`}
      />
      <span className="text-sm font-medium text-foreground">{exchange.name}</span>
      <span className={`text-xs font-medium ${isOpen ? 'text-emerald-600' : 'text-red-500'}`}>
        {isOpen ? 'Open' : 'Closed'}
      </span>
      {exchange.session_info && (
        <span className="text-xs text-muted-foreground/70">· {exchange.session_info}</span>
      )}
    </div>
  );
}

export function MarketStatus() {
  const { data } = useQuery<MarketStatusResponse>({
    queryKey: ['market-status'],
    queryFn: () => api.fetchMarketStatus(),
    refetchInterval: 5 * 60_000, // every 5 min
  });

  const queryClient = useQueryClient();

  const refreshMutation = useMutation({
    mutationFn: () => api.refreshPrices(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['portfolio'] });
      queryClient.invalidateQueries({ queryKey: ['holdings'] });
    },
  });

  return (
    <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 sm:gap-6 rounded-lg border border-border bg-card px-3 sm:px-4 py-2">
      <div className="flex flex-col sm:flex-row items-start sm:items-center gap-2 sm:gap-6">
        {data?.exchanges?.map((ex) => (
          <ExchangeIndicator key={ex.code} exchange={ex} />
        ))}
        {!data && (
          <span className="text-xs text-muted-foreground">Loading market status…</span>
        )}
      </div>

      <Button
        variant="outline"
        size="sm"
        className="w-full sm:w-auto"
        disabled={refreshMutation.isPending}
        onClick={() => refreshMutation.mutate()}
      >
        <RefreshCw
          className={`mr-1.5 h-3.5 w-3.5 ${refreshMutation.isPending ? 'animate-spin' : ''}`}
        />
        Refresh Prices
      </Button>
    </div>
  );
}
