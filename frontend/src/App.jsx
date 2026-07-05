/**
 * App.jsx — Root application component.
 *
 * Layout: ChatWindow main area.
 * Providers: TanStack QueryClientProvider.
 * On mount: initialize theme, load symbols.
 */
import { useEffect } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import useChatStore from './store/chatStore';
import useThemeStore from './store/themeStore';
import ChatWindow from './components/ChatWindow';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 2,
      refetchOnWindowFocus: false,
    },
  },
});

function AppContent() {
  const { loadSymbols } = useChatStore();
  const { init: initTheme } = useThemeStore();

  // Initialize on mount
  useEffect(() => {
    initTheme();
    loadSymbols();
  }, []);

  return (
    <div className="flex h-screen overflow-hidden
                    bg-surface-50 dark:bg-surface-950">
      {/* Main chat area */}
      <div className="flex-1 flex flex-col min-w-0">
        <ChatWindow />
      </div>
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
