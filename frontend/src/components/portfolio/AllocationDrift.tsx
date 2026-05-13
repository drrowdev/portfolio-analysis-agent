import { useQuery } from '@tanstack/react-query';
import { BarChart, Bar, XAxis, YAxis, ResponsiveContainer, Tooltip, Legend, Cell } from 'recharts';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { usePrivacy } from '@/contexts/PrivacyContext';
import { api } from '@/lib/api';

interface SectorEntry {
  sector: string;
  value_eur: number;
  weight_pct: number;
}

interface SectorBreakdownData {
  total_value_eur: number;
  sectors: SectorEntry[];
}

// Target allocation (user's strategy) - can be made configurable later
const TARGET_ALLOCATION: Record<string, number> = {
  'Technology': 50,
  'Index Fund': 25,
  'Financial Services': 15,
  'Crypto': 5,
  'Other': 5,
};

export function AllocationDrift() {
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
          <CardTitle className="text-sm font-medium">Target vs Actual</CardTitle>
        </CardHeader>
        <CardContent>
          <Skeleton className="h-[200px] w-full" />
        </CardContent>
      </Card>
    );
  }

  if (!data || data.sectors.length === 0) {
    return null;
  }

  // Build comparison data
  const allSectors = new Set([
    ...Object.keys(TARGET_ALLOCATION),
    ...data.sectors.map((s) => s.sector),
  ]);

  const chartData = Array.from(allSectors).map((sector) => {
    const actual = data.sectors.find((s) => s.sector === sector)?.weight_pct ?? 0;
    const target = TARGET_ALLOCATION[sector] ?? 0;
    const drift = actual - target;
    return { sector, actual, target, drift };
  }).sort((a, b) => b.actual - a.actual);

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium">Target vs Actual Allocation</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="h-[200px]">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData} layout="vertical" margin={{ left: 10, right: 10 }}>
              <XAxis type="number" domain={[0, 'auto']} unit="%" tick={{ fontSize: 11 }} />
              <YAxis type="category" dataKey="sector" width={100} tick={{ fontSize: 11 }} />
              <Tooltip
                formatter={(value) => {
                  if (privacyMode) return '•••';
                  const num = typeof value === 'number' ? value : Number(value);
                  return `${num.toFixed(1)}%`;
                }}
                contentStyle={{
                  backgroundColor: '#1e293b',
                  border: '1px solid #334155',
                  borderRadius: '8px',
                  color: '#e2e8f0',
                }}
              />
              <Legend wrapperStyle={{ fontSize: '12px' }} />
              <Bar dataKey="target" name="Target" fill="#475569" radius={[0, 4, 4, 0]} barSize={12} />
              <Bar dataKey="actual" name="Actual" radius={[0, 4, 4, 0]} barSize={12}>
                {chartData.map((entry) => (
                  <Cell
                    key={entry.sector}
                    fill={Math.abs(entry.drift) > 10 ? '#ef4444' : Math.abs(entry.drift) > 5 ? '#f59e0b' : '#10b981'}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Drift indicators */}
        <div className="mt-3 space-y-1.5">
          {chartData.filter((d) => Math.abs(d.drift) > 2).map((d) => (
            <div key={d.sector} className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground">{d.sector}</span>
              <span className={`font-medium tabular-nums ${d.drift > 0 ? 'text-amber-500' : 'text-blue-500'}`}>
                {d.drift > 0 ? '+' : ''}{d.drift.toFixed(1)}% {d.drift > 0 ? 'overweight' : 'underweight'}
              </span>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
