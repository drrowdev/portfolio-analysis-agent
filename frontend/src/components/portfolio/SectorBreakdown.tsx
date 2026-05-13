import { useQuery } from '@tanstack/react-query';
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip, Legend } from 'recharts';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { usePrivacy } from '@/contexts/PrivacyContext';
import { api } from '@/lib/api';

interface SectorEntry {
  sector: string;
  value_eur: number;
  weight_pct: number;
  holdings: { symbol: string; value_eur: number; weight_pct: number; industry: string }[];
}

interface CountryEntry {
  country: string;
  value_eur: number;
  weight_pct: number;
}

interface SectorBreakdownData {
  total_value_eur: number;
  sectors: SectorEntry[];
  countries: CountryEntry[];
}

const SECTOR_COLORS: Record<string, string> = {
  'Technology': '#3b82f6',
  'Financial Services': '#10b981',
  'Index Fund': '#8b5cf6',
  'Crypto': '#f59e0b',
  'Healthcare': '#ef4444',
  'Energy': '#06b6d4',
  'Consumer Cyclical': '#ec4899',
  'Industrials': '#84cc16',
  'Other': '#64748b',
};

const FALLBACK_COLORS = ['#3b82f6', '#10b981', '#8b5cf6', '#f59e0b', '#ef4444', '#06b6d4', '#ec4899', '#84cc16'];

function getSectorColor(sector: string, index: number): string {
  return SECTOR_COLORS[sector] || FALLBACK_COLORS[index % FALLBACK_COLORS.length];
}

export function SectorBreakdown() {
  const { privacyMode } = usePrivacy();

  const { data, isLoading } = useQuery({
    queryKey: ['sector-breakdown'],
    queryFn: () => api.get<SectorBreakdownData>('/portfolio/sector-breakdown'),
    staleTime: 60 * 60 * 1000, // 1h — backend caches sector data
  });

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium">Sector Breakdown</CardTitle>
        </CardHeader>
        <CardContent>
          <Skeleton className="h-[250px] w-full" />
        </CardContent>
      </Card>
    );
  }

  if (!data || data.sectors.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium">Sector Breakdown</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground text-center py-8">No data</p>
        </CardContent>
      </Card>
    );
  }

  const chartData = data.sectors.map((s) => ({
    name: s.sector,
    value: s.value_eur,
    pct: s.weight_pct,
  }));

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-medium">Sector Breakdown</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="h-[220px] sm:h-[280px]">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={chartData}
                cx="50%"
                cy="50%"
                innerRadius={55}
                outerRadius={90}
                paddingAngle={2}
                dataKey="value"
              >
                {chartData.map((entry, index) => (
                  <Cell key={entry.name} fill={getSectorColor(entry.name, index)} />
                ))}
              </Pie>
              <Tooltip
                formatter={(value, _name, props) => {
                  if (privacyMode) return '•••••';
                  const pct = props.payload?.pct;
                  const num = typeof value === 'number' ? value : Number(value);
                  const formatted = new Intl.NumberFormat('fi-FI', { style: 'currency', currency: 'EUR' }).format(num);
                  return `${formatted} (${pct}%)`;
                }}
                contentStyle={{
                  backgroundColor: '#1e293b',
                  border: '1px solid #334155',
                  borderRadius: '8px',
                  color: '#e2e8f0',
                }}
              />
              <Legend wrapperStyle={{ fontSize: '12px', color: '#94a3b8' }} />
            </PieChart>
          </ResponsiveContainer>
        </div>

        {/* Sector detail list */}
        <div className="mt-4 space-y-2">
          {data.sectors.map((s, i) => (
            <div key={s.sector} className="flex items-center justify-between text-sm">
              <div className="flex items-center gap-2">
                <div
                  className="w-3 h-3 rounded-full shrink-0"
                  style={{ backgroundColor: getSectorColor(s.sector, i) }}
                />
                <span className="text-foreground">{s.sector}</span>
              </div>
              <span className="text-muted-foreground tabular-nums font-medium">
                {privacyMode ? '•••' : `${s.weight_pct}%`}
              </span>
            </div>
          ))}
        </div>

        {/* Geography summary */}
        <div className="mt-5 pt-4 border-t border-border">
          <p className="text-xs font-medium text-muted-foreground mb-2">Geography</p>
          <div className="space-y-1.5">
            {data.countries.map((c) => (
              <div key={c.country} className="flex items-center justify-between text-sm">
                <span className="text-foreground">{c.country}</span>
                <span className="text-muted-foreground tabular-nums">
                  {privacyMode ? '•••' : `${c.weight_pct}%`}
                </span>
              </div>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
