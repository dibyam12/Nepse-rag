/**
 * App.jsx — Root application component.
 *
 * Layout: QueryHistory sidebar + ChatWindow main area.
 * Providers: TanStack QueryClientProvider.
 * On mount: initialize theme, load symbols, load conversations.
 */
import { useState, useEffect } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import useChatStore from './store/chatStore';
import useThemeStore from './store/themeStore';
import ChatWindow from './components/ChatWindow';
import QueryHistory from './components/QueryHistory';
import AuthModal from './components/AuthModal';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 2,
      refetchOnWindowFocus: false,
    },
  },
});

function AppContent() {
  const { loadSymbols, loadConversations, user } = useChatStore();
  const { init: initTheme } = useThemeStore();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [authOpen, setAuthOpen] = useState(false);

  // Initialize on mount
  useEffect(() => {
    initTheme();
    loadSymbols();
  }, []);

  // Load conversations when user logs in
  useEffect(() => {
    if (user) {
      loadConversations();
    }
  }, [user]);

  return (
    <div className="flex h-screen overflow-hidden
                    bg-surface-50 dark:bg-surface-950">
      {/* Sidebar */}
      <QueryHistory
        isOpen={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
      />

      {/* Main chat area */}
      <div className="flex-1 flex flex-col min-w-0">
        <ChatWindow
          onToggleSidebar={() => setSidebarOpen((s) => !s)}
          onOpenAuth={() => setAuthOpen(true)}
        />
      </div>

      {/* Auth modal */}
      <AuthModal
        isOpen={authOpen}
        onClose={() => setAuthOpen(false)}
      />
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AppContent />
    </QueryClientProvider>
  );
}
