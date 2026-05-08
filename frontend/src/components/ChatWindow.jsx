/**
 * ChatWindow — Main chat interface.
 *
 * Top bar: title + disclaimer + auth + dark mode toggle.
 * Middle: scrollable message list.
 * Bottom: symbol dropdown + text input + send button.
 */
import { useState, useRef, useEffect } from 'react';
import {
  Send, Menu, Sun, Moon, LogIn, LogOut, User,
  TrendingUp, ShieldAlert,
} from 'lucide-react';
import useChatStore from '../store/chatStore';
import useThemeStore from '../store/themeStore';
import MessageBubble from './MessageBubble';
import SymbolDropdown from './SymbolDropdown';

export default function ChatWindow({ onToggleSidebar, onOpenAuth }) {
  const { messages, isLoading, sendMessage, user, logout } = useChatStore();
  const { isDark, toggle: toggleTheme } = useThemeStore();
  const [input, setInput] = useState('');
  const messagesEndRef = useRef(null);
  const textareaRef = useRef(null);

  const lastAssistantMsg = [...messages].reverse().find(m => m.role === 'assistant' && m.llmProvider);

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Auto-resize textarea
  useEffect(() => {
    const ta = textareaRef.current;
    if (ta) {
      ta.style.height = 'auto';
      ta.style.height = Math.min(ta.scrollHeight, 120) + 'px';
    }
  }, [input]);

  const handleSend = () => {
    const text = input.trim();
    if (!text || isLoading) return;
    setInput('');
    sendMessage(text);
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex flex-col h-full">
      {/* ── Top Bar ────────────────────────────────── */}
      <header className="flex items-center gap-3 px-4 py-3
                         border-b border-surface-200 dark:border-surface-800
                         bg-white/80 dark:bg-surface-900/80 backdrop-blur-xl">
        {/* Sidebar toggle */}
        <button
          onClick={onToggleSidebar}
          className="p-2 rounded-xl btn-ghost"
          id="sidebar-toggle"
        >
          <Menu size={18} />
        </button>

        {/* Title + disclaimer */}
        <div className="flex items-center gap-3 flex-1 min-w-0">
          <TrendingUp size={20} className="text-brand-500 flex-shrink-0" />
          <h1 className="text-base font-bold gradient-text truncate">
            NEPSE AI Research Assistant
          </h1>
          <span className="hidden sm:flex items-center gap-1 badge badge-orange text-[10px] flex-shrink-0">
            <ShieldAlert size={10} />
            Educational Only
          </span>
        </div>

        {/* Right actions */}
        <div className="flex items-center gap-1">
          {/* Dark mode toggle */}
          <button
            onClick={toggleTheme}
            className="p-2 rounded-xl btn-ghost"
            title={isDark ? 'Light mode' : 'Dark mode'}
            id="theme-toggle"
          >
            {isDark ? <Sun size={16} /> : <Moon size={16} />}
          </button>

          {/* Auth */}
          {user ? (
            <div className="flex items-center gap-1">
              <span className="hidden sm:block text-xs font-medium text-surface-600 dark:text-surface-400 px-2">
                {user.username}
              </span>
              <button
                onClick={logout}
                className="p-2 rounded-xl btn-ghost text-surface-500"
                title="Logout"
                id="logout-btn"
              >
                <LogOut size={16} />
              </button>
            </div>
          ) : (
            <button
              onClick={onOpenAuth}
              className="flex items-center gap-1.5 px-3 py-2 rounded-xl
                         text-sm font-medium
                         text-brand-600 dark:text-brand-400
                         hover:bg-brand-50 dark:hover:bg-brand-900/20
                         transition-colors"
              id="login-btn"
            >
              <LogIn size={14} />
              <span className="hidden sm:inline">Login</span>
            </button>
          )}
        </div>
      </header>

      {/* ── Messages Area ──────────────────────────── */}
      <main className="flex-1 overflow-y-auto px-4 py-6">
        {messages.length === 0 ? (
          <EmptyState />
        ) : (
          messages.map((msg) => (
            <MessageBubble key={msg.id} message={msg} />
          ))
        )}
        <div ref={messagesEndRef} />
      </main>

      {/* ── Input Area ─────────────────────────────── */}
      <footer className="border-t border-surface-200 dark:border-surface-800
                         bg-white/80 dark:bg-surface-900/80 backdrop-blur-xl
                         px-4 py-4">
        <div className="flex items-end justify-center gap-2 max-w-4xl mx-auto w-full">
          <div className="flex-shrink-0">
            <SymbolDropdown />
          </div>
          
          <div className="flex-1 max-w-2xl relative">
              <textarea
                ref={textareaRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask about NEPSE stocks..."
                rows={1}
                className="input-field resize-none overflow-hidden text-sm min-h-[46px] py-3 shadow-sm block w-full"
                disabled={isLoading}
                id="chat-input"
              />
          </div>

          <button
            onClick={handleSend}
            disabled={!input.trim() || isLoading}
            className="flex-shrink-0 h-[46px] w-[46px] rounded-xl
                       bg-brand-500 hover:bg-brand-600
                       disabled:bg-surface-300 dark:disabled:bg-surface-700
                       text-white disabled:text-surface-500
                       transition-all duration-150
                       flex items-center justify-center shadow-md shadow-brand-500/20"
            id="send-btn"
          >
            <Send size={18} />
          </button>
        </div>
        <div className="flex items-center justify-between mt-2 max-w-4xl mx-auto w-full text-[10px] text-surface-400 dark:text-surface-500">
          <div className="flex-1 hidden sm:block">
            {lastAssistantMsg && lastAssistantMsg.llmProvider && (
              <span className="flex items-center gap-1 opacity-70">
                ⚡ {lastAssistantMsg.llmProvider}
                {lastAssistantMsg.tokenUsage ? ` • ~${lastAssistantMsg.tokenUsage} tokens` : ''}
              </span>
            )}
          </div>
          <div className="flex-shrink-0 text-center">
            Educational & research purposes only. Not financial advice.
          </div>
          <div className="flex-1 hidden sm:block" />
        </div>
      </footer>
    </div>
  );
}

function EmptyState() {
  const suggestions = [
    'Show NABIL signals today',
    'What is RSI and how to interpret it?',
    'Compare NABIL and EBL sectors',
    'Latest news about HIDCL',
  ];
  const { sendMessage, setSymbol } = useChatStore();

  return (
    <div className="flex flex-col items-center justify-center h-full text-center px-4">
      <div className="mb-6">
        <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-brand-500 to-brand-600
                        flex items-center justify-center shadow-lg shadow-brand-500/20 mb-4 mx-auto">
          <TrendingUp size={28} className="text-white" />
        </div>
        <h2 className="text-xl font-bold text-surface-800 dark:text-surface-100 mb-2">
          NEPSE AI Research Assistant
        </h2>
        <p className="text-sm text-surface-500 dark:text-surface-400 max-w-md">
          Ask questions about Nepal Stock Exchange — prices, indicators,
          sector analysis, news, and more.
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 w-full max-w-lg">
        {suggestions.map((q) => (
          <button
            key={q}
            onClick={() => {
              // Extract symbol if present
              const symbolMatch = q.match(/\b(NABIL|EBL|HIDCL|NICA|SBL|NLIC)\b/);
              if (symbolMatch) setSymbol(symbolMatch[0]);
              sendMessage(q);
            }}
            className="px-4 py-3 rounded-xl text-left text-sm
                       border border-surface-200 dark:border-surface-700
                       hover:border-brand-400 dark:hover:border-brand-500
                       hover:bg-brand-50/50 dark:hover:bg-brand-900/10
                       text-surface-600 dark:text-surface-400
                       transition-all duration-200"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}
