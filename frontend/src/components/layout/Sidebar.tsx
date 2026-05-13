import { LayoutDashboard, Briefcase, Newspaper, Bell, Settings, Wand2, Sparkles, TrendingUp, Target, History } from 'lucide-react';
import { Link, useRouterState } from '@tanstack/react-router';
import { cn, formatRelativeDate } from '@/lib/utils';
import { api } from '@/lib/api';
import { useQuery } from '@tanstack/react-query';
import { useState, useEffect } from 'react';

const navItems = [
  { to: '/' as const, label: 'Dashboard', icon: LayoutDashboard },
  { to: '/holdings' as const, label: 'Holdings', icon: Briefcase },
  { to: '/transactions' as const, label: 'Transactions', icon: History },
  { to: '/goals' as const, label: 'Goals', icon: Target },
  { to: '/news' as const, label: 'News', icon: Newspaper },
  { to: '/alerts' as const, label: 'Alerts', icon: Bell },
  { to: '/analysis' as const, label: 'AI Analysis', icon: Sparkles },
  { to: '/wizard' as const, label: 'Import Wizard', icon: Wand2 },
  { to: '/settings' as const, label: 'Settings', icon: Settings },
];

export function Sidebar() {
  const routerState = useRouterState();
  const currentPath = routerState.location.pathname;

  // Track when the portfolio summary was last successfully fetched
  const { dataUpdatedAt } = useQuery({
    queryKey: ['portfolio', 'summary'],
    queryFn: () => api.fetchPortfolioSummary(),
    staleTime: 5 * 60_000,   // 5 min — avoid redundant refetches
    refetchInterval: 5 * 60_000,
  });

  // Re-render every 30s to keep relative time fresh
  const [, setTick] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => setTick((t) => t + 1), 30_000);
    return () => clearInterval(timer);
  }, []);

  const syncText = dataUpdatedAt
    ? `Last sync: ${formatRelativeDate(new Date(dataUpdatedAt).toISOString())}`
    : 'Syncing…';

  return (
    <aside className="hidden md:flex w-60 flex-col border-r border-border bg-card">
      <div className="flex h-14 items-center border-b border-border px-4">
        <TrendingUp className="h-5 w-5 text-emerald-500 mr-2" />
        <span className="text-lg font-bold text-foreground">Portfolio Agent</span>
      </div>
      <nav className="flex-1 space-y-1 p-3">
        {navItems.map((item) => {
          const isActive = currentPath === item.to || (item.to !== '/' && currentPath.startsWith(item.to));
          return (
            <Link
              key={item.to}
              to={item.to}
              className={cn(
                'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                isActive
                  ? 'bg-emerald-600/15 text-emerald-500'
                  : 'text-muted-foreground hover:bg-accent hover:text-foreground'
              )}
            >
              <item.icon className="h-4 w-4" />
              {item.label}
            </Link>
          );
        })}
      </nav>
      <div className="border-t border-border p-4">
        <p className="text-xs text-muted-foreground">{syncText}</p>
      </div>
    </aside>
  );
}
