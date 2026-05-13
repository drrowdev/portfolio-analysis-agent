import { lazy, Suspense } from 'react';
import { useDashboard } from '@/hooks/useDashboard';
import { DailySummaryCard } from '@/components/portfolio/DailySummaryCard';
import { PortfolioSummary } from '@/components/portfolio/PortfolioSummary';
import { HoldingsTable } from '@/components/portfolio/HoldingsTable';
import { AllocationChart } from '@/components/portfolio/AllocationChart';
import { AccountBreakdown } from '@/components/portfolio/AccountBreakdown';
import { MarketStatus } from '@/components/portfolio/MarketStatus';
import { CashAvailableCard } from '@/components/portfolio/CashAvailableCard';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { FolderOpen } from 'lucide-react';
import { Link } from '@tanstack/react-router';
import { Button } from '@/components/ui/button';

// Lazy-load below-fold heavy components (charts, calendars)
const PerformanceChart = lazy(() => import('@/components/portfolio/PerformanceChart').then(m => ({ default: m.PerformanceChart })));
const SectorBreakdown = lazy(() => import('@/components/portfolio/SectorBreakdown').then(m => ({ default: m.SectorBreakdown })));
const AllocationDrift = lazy(() => import('@/components/portfolio/AllocationDrift').then(m => ({ default: m.AllocationDrift })));
const EarningsCalendar = lazy(() => import('@/components/portfolio/EarningsCalendar').then(m => ({ default: m.EarningsCalendar })));
const RealizedGainsCard = lazy(() => import('@/components/portfolio/RealizedGainsCard').then(m => ({ default: m.RealizedGainsCard })));
const DividendsCard = lazy(() => import('@/components/portfolio/DividendsCard').then(m => ({ default: m.DividendsCard })));

function LazyCardFallback() {
  return <Card><CardContent className="pt-6"><Skeleton className="h-48 w-full" /></CardContent></Card>;
}

function DashboardSkeleton() {
  return (
    <div className="space-y-6">
      <div>
        <Skeleton className="h-8 w-40" />
        <Skeleton className="h-4 w-64 mt-2" />
      </div>
      {/* Market status skeleton */}
      <Skeleton className="h-10 w-full rounded-lg" />
      {/* Summary cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[...Array(4)].map((_, i) => (
          <Card key={i}>
            <CardContent className="pt-6">
              <Skeleton className="h-4 w-24 mb-3" />
              <Skeleton className="h-7 w-32" />
            </CardContent>
          </Card>
        ))}
      </div>
      {/* Daily summary skeleton */}
      <Card>
        <CardContent className="pt-6">
          <Skeleton className="h-4 w-48 mb-3" />
          <Skeleton className="h-20 w-full" />
        </CardContent>
      </Card>
      {/* Performance chart skeleton */}
      <Card>
        <CardHeader><Skeleton className="h-4 w-40" /></CardHeader>
        <CardContent><Skeleton className="h-64 w-full" /></CardContent>
      </Card>
      {/* Holdings + sidebar */}
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <Card>
            <CardHeader><Skeleton className="h-4 w-24" /></CardHeader>
            <CardContent className="space-y-3">
              {[...Array(5)].map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </CardContent>
          </Card>
        </div>
        <div className="space-y-6">
          <Card><CardContent className="pt-6"><Skeleton className="h-48 w-full" /></CardContent></Card>
          <Card><CardContent className="pt-6"><Skeleton className="h-32 w-full" /></CardContent></Card>
        </div>
      </div>
    </div>
  );
}

export function DashboardPage() {
  const { data, isLoading, error } = useDashboard();

  const summary = data?.summary;
  const holdings = data?.holdings;
  const accounts = data?.accounts ?? [];

  const cryptoAccountIds = new Set(
    accounts.filter((a) => a.account_type === 'crypto').map((a) => a.id)
  );

  if (isLoading) {
    return <DashboardSkeleton />;
  }

  if (error || !summary || summary.accounts.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-64 space-y-4">
        <FolderOpen className="h-12 w-12 text-muted-foreground" />
        <h3 className="text-lg font-medium text-foreground">No portfolio data yet</h3>
        <p className="text-sm text-muted-foreground">
          Upload your broker statements to get started.
        </p>
        <Link to="/wizard">
          <Button className="bg-emerald-600 hover:bg-emerald-700">Go to Import Wizard</Button>
        </Link>
      </div>
    );
  }

  const accountNames: Record<string, string> = Object.fromEntries(
    summary.accounts.map((a) => [a.account_id, a.account_name])
  );

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-foreground">Dashboard</h2>
        <p className="text-sm text-muted-foreground">Your portfolio overview at a glance</p>
      </div>

      <MarketStatus />

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3 sm:gap-4">
        <div className="col-span-2 md:col-span-3 lg:col-span-4">
          <PortfolioSummary summary={summary} />
        </div>
        <CashAvailableCard />
      </div>

      <DailySummaryCard />

      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium">Performance vs S&amp;P 500</CardTitle>
        </CardHeader>
        <CardContent>
          <Suspense fallback={<Skeleton className="h-64 w-full" />}>
            <PerformanceChart />
          </Suspense>
        </CardContent>
      </Card>

      {/* Holdings table — full width */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium">Holdings</CardTitle>
        </CardHeader>
        <CardContent>
          {holdings && holdings.length > 0 ? (
            <HoldingsTable
              holdings={holdings}
              accountNames={accountNames}
              cryptoAccountIds={cryptoAccountIds}
            />
          ) : (
            <p className="text-sm text-muted-foreground py-4">No detailed holdings data available.</p>
          )}
        </CardContent>
      </Card>

      {/* Row: Allocation charts + Earnings */}
      <Suspense fallback={<div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3"><LazyCardFallback /><LazyCardFallback /><LazyCardFallback /></div>}>
        <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
          <AllocationChart holdings={summary.top_holdings} />
          <SectorBreakdown />
          <AllocationDrift />
        </div>
      </Suspense>

      {/* Row: Financial metrics + Calendar */}
      <Suspense fallback={<div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3"><LazyCardFallback /><LazyCardFallback /><LazyCardFallback /></div>}>
        <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
          <RealizedGainsCard />
          <DividendsCard />
          <EarningsCalendar />
        </div>
      </Suspense>

      {/* Row: Account breakdown */}
      <div className="grid gap-6 md:grid-cols-2">
        <AccountBreakdown accounts={summary.accounts} />
      </div>
    </div>
  );
}
