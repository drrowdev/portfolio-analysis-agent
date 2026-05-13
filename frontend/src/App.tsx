import { createRouter, createRoute, createRootRoute } from '@tanstack/react-router';
import { Layout } from '@/components/layout/Layout';
import { DashboardPage } from '@/pages/DashboardPage';
import { HoldingsPage } from '@/pages/HoldingsPage';
import { TransactionsPage } from '@/pages/TransactionsPage';
import { WizardPage } from '@/pages/WizardPage';
import { NewsPage } from '@/pages/NewsPage';
import { AlertsPage } from '@/pages/AlertsPage';
import { AnalysisPage } from '@/pages/AnalysisPage';
import { SettingsPage } from '@/pages/SettingsPage';
import { GoalsPage } from '@/pages/GoalsPage';
import { PositionDetailPage } from '@/pages/PositionDetailPage';

const rootRoute = createRootRoute({
  component: Layout,
});

const dashboardRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  component: DashboardPage,
});

const holdingsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/holdings',
  component: HoldingsPage,
});

const transactionsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/transactions',
  component: TransactionsPage,
});

const wizardRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/wizard',
  component: WizardPage,
});

const newsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/news',
  component: NewsPage,
});

const alertsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/alerts',
  component: AlertsPage,
});

const analysisRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/analysis',
  component: AnalysisPage,
});

const settingsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/settings',
  component: SettingsPage,
});

const goalsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/goals',
  component: GoalsPage,
});

const positionRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/position/$symbol',
  component: PositionDetailPage,
});

const routeTree = rootRoute.addChildren([
  dashboardRoute,
  holdingsRoute,
  transactionsRoute,
  wizardRoute,
  newsRoute,
  alertsRoute,
  analysisRoute,
  settingsRoute,
  goalsRoute,
  positionRoute,
]);

export const router = createRouter({ routeTree });

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router;
  }
}
