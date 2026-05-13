import { StrictMode, useState, useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider } from '@tanstack/react-router';
import { router } from './App.tsx';
import { PrivacyProvider } from './contexts/PrivacyContext';
import { LoginGate } from './components/auth/LoginGate';
import { api } from './lib/api';
import './index.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 2 * 60 * 1000,       // 2 min default — data shown instantly on revisit
      gcTime: 10 * 60 * 1000,          // keep unused cache 10 min
    },
  },
});

function App() {
  const [authState, setAuthState] = useState<'checking' | 'authenticated' | 'unauthenticated'>('checking');

  useEffect(() => {
    api.checkAuth()
      .then((data) => setAuthState(data.authenticated ? 'authenticated' : 'unauthenticated'))
      .catch(() => setAuthState('unauthenticated'));
  }, []);

  if (authState === 'checking') return null; // Flash-free — resolves in <5ms (same origin)

  if (authState === 'unauthenticated') {
    return <LoginGate onSuccess={() => setAuthState('authenticated')} />;
  }

  return (
    <PrivacyProvider>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </PrivacyProvider>
  );
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
