import { useState } from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';
import { Loader2 } from 'lucide-react';
import { usePerformance } from '@/hooks/usePerformance';
import { usePrivacy } from '@/contexts/PrivacyContext';

const PERIODS = ['1m', '3m', '6m', 'ytd', '1y', 'all'] as const;
const PERIOD_LABELS: Record<string, string> = {
  '1m': '1M',
  '3m': '3M',
  '6m': '6M',
  ytd: 'YTD',
  '1y': '1Y',
  all: 'ALL',
};

function formatDate(dateStr: string, period: string): string {
  const d = new Date(dateStr);
  if (['1m', '3m'].includes(period)) {
    // Day + month, fi-FI numeric (e.g. "13.5.")
    return d.toLocaleDateString('fi-FI', { day: 'numeric', month: 'numeric' });
  }
  // Month + year for longer ranges (e.g. "5/2026")
  return d.toLocaleDateString('fi-FI', { month: 'numeric', year: 'numeric' });
}

interface CustomTooltipProps {
  active?: boolean;
  payload?: Array<{ name: string; value: number; color: string }>;
  label?: string;
  privacyMode?: boolean;
}

function CustomTooltip({ active, payload, label, privacyMode }: CustomTooltipProps) {
  if (!active || !payload || !label) return null;
  const d = new Date(label);
  const formatted = d.toLocaleDateString('fi-FI', {
    day: 'numeric',
    month: 'numeric',
    year: 'numeric',
  });
  return (
    <div
      style={{
        backgroundColor: '#1e293b',
        border: '1px solid #334155',
        borderRadius: '8px',
        padding: '10px 14px',
        color: '#e2e8f0',
        fontSize: '13px',
      }}
    >
      <p className="font-medium mb-1">{formatted}</p>
      {payload.map((entry) => (
        <p key={entry.name} style={{ color: entry.color }}>
          {entry.name}: {privacyMode ? '•••••' : `${entry.value >= 0 ? '+' : ''}${entry.value.toFixed(2)}%`}
        </p>
      ))}
    </div>
  );
}

export function PerformanceChart() {
  const [period, setPeriod] = useState<string>('1y');
  const { data, isLoading, error } = usePerformance(period);
  const { privacyMode } = usePrivacy();

  const chartData = data?.data ?? [];
  const lastPoint = chartData.length > 0 ? chartData[chartData.length - 1] : null;
  const diff = lastPoint
    ? lastPoint.portfolio_return_pct - lastPoint.sp500_return_pct
    : 0;
  const beating = diff >= 0;

  return (
    <div>
      {/* Period selector + beating/trailing badge */}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div className="inline-flex rounded-lg border border-border overflow-hidden">
          {PERIODS.map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className={`px-2 py-1 text-[10px] sm:px-3 sm:py-1.5 sm:text-xs font-medium transition-colors ${
                period === p
                  ? 'bg-emerald-600 text-white'
                  : 'bg-card text-muted-foreground hover:bg-muted'
              }`}
            >
              {PERIOD_LABELS[p]}
            </button>
          ))}
        </div>

        {lastPoint && !isLoading && (
          <span
            className={`inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs font-medium ${
              beating
                ? 'bg-emerald-500/15 text-emerald-400'
                : 'bg-red-500/15 text-red-400'
            }`}
          >
            {beating ? '▲' : '▼'}{' '}
            {beating ? 'Beating' : 'Trailing'} S&P 500 by{' '}
            {privacyMode ? '•••••' : `${Math.abs(diff).toFixed(1)}%`}
          </span>
        )}
      </div>

      {/* Chart */}
      {isLoading ? (
        <div className="flex items-center justify-center h-64">
          <Loader2 className="h-6 w-6 animate-spin text-emerald-500" />
          <span className="ml-2 text-sm text-muted-foreground">
            Loading performance data…
          </span>
        </div>
      ) : error ? (
        <div className="flex items-center justify-center h-64">
          <p className="text-sm text-muted-foreground">
            Unable to load performance data.
          </p>
        </div>
      ) : chartData.length === 0 ? (
        <div className="flex items-center justify-center h-64">
          <p className="text-sm text-muted-foreground">
            No performance data available for this period. Upload transactions to get started.
          </p>
        </div>
      ) : (
        <div className="h-[250px] sm:h-[350px]">
          <ResponsiveContainer width="100%" height="100%">
          <LineChart
            data={chartData}
            margin={{ top: 5, right: 10, left: 0, bottom: 5 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
            <XAxis
              dataKey="date"
              tickFormatter={(v: string) => formatDate(v, period)}
              tick={{ fill: '#94a3b8', fontSize: 11 }}
              stroke="#334155"
              minTickGap={40}
            />
            <YAxis
              tickFormatter={(v: number) => privacyMode ? '•••' : `${v}%`}
              tick={{ fill: '#94a3b8', fontSize: 11 }}
              stroke="#334155"
              width={50}
            />
            <Tooltip content={<CustomTooltip privacyMode={privacyMode} />} />
            <Legend
              wrapperStyle={{ fontSize: '12px', color: '#94a3b8' }}
            />
            <Line
              type="monotone"
              dataKey="portfolio_return_pct"
              name="Portfolio"
              stroke="#10b981"
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4 }}
            />
            <Line
              type="monotone"
              dataKey="sp500_return_pct"
              name="S&P 500"
              stroke="#64748b"
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4 }}
            />
          </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
