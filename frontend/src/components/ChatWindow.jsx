/**
 * ChatWindow — Main chat interface.
 *
 * Top bar: title + disclaimer + auth + dark mode toggle.
 * Middle: scrollable message list with premium styling.
 * Bottom: symbol chip + text input + send button (kept as-is).
 */
import { useState, useRef, useEffect } from 'react';
import {
  Send, Sun, Moon,
  TrendingUp, ShieldAlert, X
} from 'lucide-react';
import useChatStore from '../store/chatStore';
import useThemeStore from '../store/themeStore';
import MessageBubble from './MessageBubble';

export default function ChatWindow() {
  const { messages, isLoading, sendMessage, lastSymbol, setLastSymbol } = useChatStore();
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
        <div className="flex items-center gap-2 flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-xl bg-brand-500/10 flex items-center justify-center border border-brand-500/20">
              <TrendingUp className="w-5 h-5 text-brand-600 dark:text-brand-400" />
            </div>
            <div>
              <h1 className="font-semibold text-surface-900 dark:text-surface-50">NEPSE AI</h1>
              <p className="text-[10px] text-surface-500 font-medium">Research Assistant</p>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* Disclaimer Banner - Hidden on mobile */}
          <div className="hidden md:flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-amber-500/10 border border-amber-500/20">
            <ShieldAlert className="w-3.5 h-3.5 text-amber-600 dark:text-amber-500" />
            <span className="text-xs font-medium text-amber-700 dark:text-amber-500">Not financial advice</span>
          </div>

          <button
            onClick={toggleTheme}
            className="p-2 text-surface-500 hover:text-surface-900 dark:hover:text-surface-100
                       hover:bg-surface-100 dark:hover:bg-surface-800 rounded-xl transition-colors"
            title="Toggle theme"
          >
            {isDark ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
          </button>
        </div>
      </header>

      {/* ── Messages Area ──────────────────────────── */}
      <main className="flex-1 overflow-y-auto px-4 py-6 chat-scroll">
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
          <div className="flex-1 max-w-2xl relative flex flex-col gap-2">
              {lastSymbol && (
                <div className="absolute -top-10 left-2">
                  <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium bg-brand-50 dark:bg-brand-500/10 text-brand-700 dark:text-brand-400 border border-brand-200 dark:border-brand-500/20 shadow-sm">
                    {lastSymbol}
                    <button onClick={() => setLastSymbol(null)} className="hover:text-brand-900 dark:hover:text-brand-200 focus:outline-none rounded-full p-0.5 hover:bg-brand-200 dark:hover:bg-brand-500/30 transition-colors">
                      <X className="w-3 h-3" />
                    </button>
                  </span>
                </div>
              )}
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
    { icon: '📈', title: 'Price + News', text: 'Tell me the price of NABIL today and the latest news' },
    { icon: '⚖️', title: 'Compare Stocks', text: 'Compare NICA and NCCB fundamentals' },
    { icon: '🏦', title: 'Sector Analysis', text: 'Top gainers in commercial banking today?' },
    { icon: '📖', title: 'Learn Indicators', text: 'Explain RSI and what it means for HIDCL' },
  ];
  const { sendMessage, setSymbol } = useChatStore();

  return (
    <div className="welcome-screen">
      {/* Logo */}
      <div className="welcome-logo-wrap">
        <svg viewBox="0 0 52 52" fill="none" width="52" height="52">
          <rect x="4" y="4" width="18" height="18" rx="3" fill="currentColor" opacity="0.2"/>
          <rect x="4" y="30" width="18" height="18" rx="3" fill="currentColor" opacity="0.5"/>
          <rect x="30" y="4" width="18" height="18" rx="3" fill="currentColor" opacity="0.5"/>
          <rect x="30" y="30" width="18" height="18" rx="3" fill="currentColor"/>
          <path d="M13 13 L39 39" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" opacity="0.35"/>
        </svg>
      </div>

      <h1 className="welcome-title">NEPSE AI Research Assistant</h1>
      <p className="welcome-sub">
        Ask questions about NEPSE stocks, technical indicators, sector data, and market news.
        Powered by Graph RAG + Agentic RAG.
      </p>

      <div className="suggestion-grid">
        {suggestions.map((s) => (
          <button
            key={s.text}
            className="suggestion-card"
            onClick={() => {
              const symbolMatch = s.text.match(/\b(NABIL|EBL|HIDCL|NICA|SBL|NLIC|NCCB)\b/);
              if (symbolMatch) setSymbol(symbolMatch[0]);
              sendMessage(s.text);
            }}
          >
            <div className="s-title">{s.icon} {s.title}</div>
            <div className="s-text">{s.text}</div>
          </button>
        ))}
      </div>
    </div>
  );
}
