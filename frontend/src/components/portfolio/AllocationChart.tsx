import type { AllocationEntry } from '@/types/portfolio';
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip, Legend } from 'recharts';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { usePrivacy } from '@/contexts/PrivacyContext';

interface AllocationChartProps {
  holdings: AllocationEntry[];
}

const COLORS = ['#10b981', '#3b82f6', '#8b5cf6', '#f59e0b', '#ef4444', '#06b6d4', '#ec4899', '#84cc16'];

export function AllocationChart({ holdings }: AllocationChartProps) {
  const { privacyMode } = usePrivacy();

  const data = holdings
    .filter((h) => h.value_eur > 0)
    .map((h) => ({
      name: h.symbol,
      value: h.value_eur,
    }))
    .sort((a, b) => b.value - a.value);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-medium">Portfolio Allocation</CardTitle>
      </CardHeader>
      <CardContent>
        {data.length === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-8">No holdings data</p>
        ) : (
          <div className="h-[220px] sm:h-[300px]">
            <ResponsiveContainer width="100%" height="100%">
            <PieChart margin={{ top: 10, right: 0, bottom: 0, left: 0 }}>
              <Pie
                data={data}
                cx="50%"
                cy="45%"
                innerRadius={50}
                outerRadius={80}
                paddingAngle={2}
                dataKey="value"
              >
                {data.map((_entry, index) => (
                  <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip
                formatter={(value) => {
                  if (privacyMode) return '•••••';
                  const num = typeof value === 'number' ? value : Number(value);
                  return new Intl.NumberFormat('fi-FI', { style: 'currency', currency: 'EUR' }).format(num);
                }}
                contentStyle={{
                  backgroundColor: '#1e293b',
                  border: '1px solid #334155',
                  borderRadius: '8px',
                  color: '#e2e8f0',
                }}
              />
              <Legend
                wrapperStyle={{ fontSize: '12px', color: '#94a3b8' }}
              />
            </PieChart>
            </ResponsiveContainer>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
