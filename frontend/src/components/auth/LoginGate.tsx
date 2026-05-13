import { useState } from 'react';
import { TrendingUp, Lock } from 'lucide-react';
import { api } from '@/lib/api';

interface LoginGateProps {
  onSuccess: () => void;
}

export function LoginGate({ onSuccess }: LoginGateProps) {
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      await api.login(password);
      onSuccess();
    } catch {
      setError('Invalid password');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm space-y-6 text-center">
        <div className="flex items-center justify-center gap-2">
          <TrendingUp className="h-8 w-8 text-emerald-500" />
          <h1 className="text-2xl font-bold text-foreground">Portfolio</h1>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="relative">
            <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Enter password"
              autoFocus
              className="w-full rounded-lg border border-border bg-card pl-10 pr-4 py-3 text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-emerald-500/50 focus:border-emerald-500"
            />
          </div>

          {error && (
            <p className="text-sm text-red-500">{error}</p>
          )}

          <button
            type="submit"
            disabled={loading || !password}
            className="w-full rounded-lg bg-emerald-600 px-4 py-3 font-medium text-white hover:bg-emerald-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {loading ? 'Verifying...' : 'Unlock'}
          </button>
        </form>
      </div>
    </div>
  );
}
