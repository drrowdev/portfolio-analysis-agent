import { TrendingUp, Eye, EyeOff } from 'lucide-react';
import { UserMenu } from '@/components/auth/UserMenu';
import { usePrivacy } from '@/contexts/PrivacyContext';

export function Header() {
  const { privacyMode, togglePrivacy } = usePrivacy();

  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-2 sm:gap-4 border-b border-border bg-background/95 px-3 sm:px-6 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="flex flex-1 items-center gap-2 min-w-0">
        <TrendingUp className="h-5 w-5 text-emerald-500 shrink-0" />
        <h1 className="text-base sm:text-lg font-semibold text-foreground truncate">Portfolio Analysis Agent</h1>
      </div>
      <div className="flex items-center gap-4">
        <button
          onClick={togglePrivacy}
          title={privacyMode ? 'Show values' : 'Hide values'}
          className="inline-flex items-center justify-center rounded-md p-2 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
        >
          {privacyMode ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
        </button>
        <UserMenu />
      </div>
    </header>
  );
}
