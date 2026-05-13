import { LayoutDashboard, Briefcase, Newspaper, Bell, Sparkles, Wand2, History } from 'lucide-react';
import { Link, useRouterState } from '@tanstack/react-router';
import { cn } from '@/lib/utils';

const navItems = [
  { to: '/' as const, label: 'Dashboard', icon: LayoutDashboard },
  { to: '/holdings' as const, label: 'Holdings', icon: Briefcase },
  { to: '/transactions' as const, label: 'History', icon: History },
  { to: '/news' as const, label: 'News', icon: Newspaper },
  { to: '/alerts' as const, label: 'Alerts', icon: Bell },
  { to: '/analysis' as const, label: 'Analysis', icon: Sparkles },
  { to: '/wizard' as const, label: 'Wizard', icon: Wand2 },
];

export function MobileNav() {
  const routerState = useRouterState();
  const currentPath = routerState.location.pathname;

  return (
    <nav className="md:hidden fixed bottom-0 left-0 right-0 z-50 bg-card border-t border-border">
      <div className="flex items-center justify-around">
        {navItems.map((item) => {
          const isActive = currentPath === item.to || (item.to !== '/' && currentPath.startsWith(item.to));
          return (
            <Link
              key={item.to}
              to={item.to}
              className={cn(
                'flex flex-col items-center gap-0.5 px-2 py-2 text-[10px] font-medium transition-colors min-w-0',
                isActive
                  ? 'text-emerald-500'
                  : 'text-muted-foreground'
              )}
            >
              <item.icon className="h-5 w-5" />
              <span className="truncate">{item.label}</span>
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
