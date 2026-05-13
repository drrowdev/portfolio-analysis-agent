import { Outlet } from '@tanstack/react-router';
import { Header } from './Header';
import { Sidebar } from './Sidebar';
import { MobileNav } from './MobileNav';
import { Toaster } from '@/components/ui/toaster';
import { ChatPanel } from '@/components/chat/ChatPanel';

export function Layout() {
  return (
    <div className="flex h-screen bg-background text-foreground">
      <Sidebar />
      <div className="flex flex-1 flex-col overflow-hidden">
        <Header />
        <main className="flex-1 overflow-y-auto p-3 sm:p-6 pb-20 md:pb-6">
          <Outlet />
        </main>
      </div>
      <Toaster />
      <MobileNav />
      <ChatPanel />
    </div>
  );
}
