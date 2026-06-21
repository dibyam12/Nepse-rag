/**
 * Chat store — manages messages, conversations, auth, and symbols.
 *
 * Uses Zustand for lightweight state management.
 * Auth state persisted to localStorage.
 */
import { create } from 'zustand';
import api from '../api/client';

const useChatStore = create((set, get) => ({
  // ── Chat State ────────────────────────────────────
  messages: [],
  isLoading: false,
  selectedSymbol: '',
  lastSymbol: null,
  symbols: [],

  // ── Token buffer state (50ms batching for smooth typewriter effect) ──
  _tokenBuffers: {},   // { [messageId: string]: string[] }
  _flushTimers:  {},   // { [messageId: string]: timeoutId }

  // ── Conversation State ────────────────────────────
  conversations: [],
  activeConversationId: null,

  // ── Auth State ────────────────────────────────────
  user: JSON.parse(localStorage.getItem('nepse_user') || 'null'),
  token: localStorage.getItem('nepse_token') || null,

  // ── Symbol Actions ────────────────────────────────

  setSymbol: (sym) => set({ selectedSymbol: sym }),
  setLastSymbol: (sym) => set({ lastSymbol: sym }),

  loadSymbols: async () => {
    try {
      const res = await api.get('/symbols/');
      set({ symbols: res.data });
    } catch (err) {
      console.error('Failed to load symbols:', err);
    }
  },

  // ── Message Actions ───────────────────────────────

  addUserMessage: (content) => {
    const msg = {
      id: Date.now(),
      role: 'user',
      content,
      created_at: new Date().toISOString(),
    };
    set((s) => ({ messages: [...s.messages, msg] }));
    return msg.id;
  },

  addAssistantPlaceholder: () => {
    const msg = {
      id: Date.now() + 1,
      role: 'assistant',
      content: '',
      isStreaming: true,
      statusMessage: '',
      statusSteps: [],
      signals: null,
      citations: null,
      toolsUsed: null,
      routeUsed: null,
      llmProvider: null,
      tokenUsage: null,
      latencyMs: null,
      created_at: new Date().toISOString(),
    };
    set((s) => ({ messages: [...s.messages, msg] }));
    return msg.id;
  },

  appendToken: (messageId, token) => {
    const s = get();

    // Accumulate token into the buffer
    const buf = s._tokenBuffers[messageId] || [];
    buf.push(token);

    // Cancel any pending flush timer for this message
    const existingTimer = s._flushTimers[messageId];
    if (existingTimer) clearTimeout(existingTimer);

    // Schedule a flush in 50ms
    const timerId = setTimeout(() => {
      const current = get();
      const pending = (current._tokenBuffers[messageId] || []).join('');
      if (!pending) return;
      set((state) => ({
        _tokenBuffers: { ...state._tokenBuffers, [messageId]: [] },
        _flushTimers:  { ...state._flushTimers,  [messageId]: null },
        messages: state.messages.map((m) =>
          m.id === messageId
            ? { ...m, content: m.content + pending }
            : m
        ),
      }));
    }, 50);

    set((s) => ({
      _tokenBuffers: { ...s._tokenBuffers, [messageId]: buf },
      _flushTimers:  { ...s._flushTimers,  [messageId]: timerId },
    }));
  },

  finalizeMessage: (messageId, data) => {
    // Force-flush any remaining buffered tokens before marking done
    const state = get();
    const timer = state._flushTimers[messageId];
    if (timer) clearTimeout(timer);
    const remaining = (state._tokenBuffers[messageId] || []).join('');

    set((s) => ({
      _tokenBuffers: { ...s._tokenBuffers, [messageId]: [] },
      _flushTimers:  { ...s._flushTimers,  [messageId]: null },
      messages: s.messages.map((m) =>
        m.id === messageId
          ? {
              ...m,
              // Append any unflushed tokens first
              content: m.content + remaining,
              isStreaming: false,
              statusMessage: '',
              statusSteps: [],
              signals:     data.signals     || m.signals,
              citations:   data.citations   || m.citations,
              toolsUsed:   data.toolsUsed   || m.toolsUsed,
              routeUsed:   data.routeUsed   || m.routeUsed,
              llmProvider: data.llmProvider || m.llmProvider,
              tokenUsage:  data.tokenUsage  || m.tokenUsage,
              latencyMs:   data.latencyMs   || m.latencyMs,
            }
          : m
      ),
      isLoading: false,
    }));
  },

  setNonStreamingResponse: (messageId, result) => {
    set((s) => ({
      messages: s.messages.map((m) =>
        m.id === messageId
          ? {
              ...m,
              content: result.answer || '',
              isStreaming: false,
              signals: result.signals || null,
              citations: result.citations || null,
              toolsUsed: result.tools_called || null,
              routeUsed: result.route_used || null,
              llmProvider: result.llm_provider_used || null,
              tokenUsage: result.tokens_used || null,
              latencyMs: result.latency_ms || null,
            }
          : m
      ),
      isLoading: false,
      activeConversationId: result.conversation_id || s.activeConversationId,
    }));
  },

  sendMessage: async (question) => {
    const { selectedSymbol, activeConversationId, user } = get();
    set({ isLoading: true });

    // Add user message to UI
    get().addUserMessage(question);

    // Add assistant placeholder
    const assistantId = get().addAssistantPlaceholder();

    // Try SSE streaming first
    try {
      const symbolToSend = selectedSymbol || get().lastSymbol || "";
      const params = new URLSearchParams({
        question,
        symbol: symbolToSend,
        ...(activeConversationId && { conversation_id: activeConversationId }),
      });

      const token = localStorage.getItem('nepse_token');
      // Note: EventSource doesn't support custom headers,
      // so auth for streaming uses query params or session cookies.
      // For simplicity, we pass token as query param for SSE.
      if (token) {
        params.append('token', token);
      }

      const url = `/api/query/stream/?${params.toString()}`;
      const eventSource = new EventSource(url);

      let signals = null;
      let citations = null;
      let routeUsed = null;
      let toolsUsed = null;
      let llmProvider = null;
      let tokenUsage = null;
      let latencyMs = null;

      eventSource.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          switch (data.type) {
            case 'token':
              get().appendToken(assistantId, data.content);
              break;
            case 'status':
              set((s) => ({
                messages: s.messages.map((m) =>
                  m.id === assistantId
                    ? {
                        ...m,
                        statusMessage: data.message,
                        // Accumulate steps for timeline — deduplicate
                        statusSteps: (m.statusSteps || []).includes(data.message)
                          ? m.statusSteps
                          : [...(m.statusSteps || []), data.message],
                      }
                    : m
                ),
              }));
              break;
            case 'signals':
              signals = data.data;
              if (signals?.symbol) {
                set({ lastSymbol: signals.symbol });
              }
              if (signals?.price_cards?.length > 0) {
                set({ lastSymbol: signals.price_cards[0].symbol });
              }
              break;
            case 'citations':
              citations = data.data;
              break;
            case 'route':
              routeUsed = data.data;
              break;
            case 'tools':
              toolsUsed = data.data;
              break;
            case 'provider':
              llmProvider = data.data;
              tokenUsage = data.tokens || null;
              break;
            case 'done':
              latencyMs = data.latency_ms;
              get().finalizeMessage(assistantId, {
                signals, citations, routeUsed,
                toolsUsed, llmProvider, tokenUsage, latencyMs,
              });
              eventSource.close();
              // Refresh conversations if authenticated
              if (user) get().loadConversations();
              break;
            case 'error':
              get().appendToken(assistantId, data.message || 'An error occurred.');
              get().finalizeMessage(assistantId, {});
              eventSource.close();
              break;
          }
        } catch (e) {
          console.error('SSE parse error:', e);
        }
      };

      eventSource.onerror = () => {
        eventSource.close();
        // Fallback to non-streaming POST
        get()._fallbackPost(question, assistantId);
      };

    } catch (err) {
      // Fallback to non-streaming POST
      get()._fallbackPost(question, assistantId);
    }
  },

  _fallbackPost: async (question, assistantId) => {
    const { selectedSymbol, activeConversationId } = get();
    try {
      const res = await api.post('/query/', {
        question,
        symbol: selectedSymbol,
        conversation_id: activeConversationId,
      });
      get().setNonStreamingResponse(assistantId, res.data);
    } catch (err) {
      const errorMsg = err.response?.data?.error
        || 'Failed to get response. Please try again.';
      get().setNonStreamingResponse(assistantId, {
        answer: errorMsg + '\n\nDISCLAIMER: This is for educational purposes only. Not financial advice.',
      });
    }
  },

  clearChat: () => {
    set({
      messages: [],
      activeConversationId: null,
    });
  },

  // ── Auth Actions ──────────────────────────────────

  login: async (username, password) => {
    const res = await api.post('/auth/login/', { username, password });
    const { token, user } = res.data;
    localStorage.setItem('nepse_token', token);
    localStorage.setItem('nepse_user', JSON.stringify(user));
    set({ token, user });
    // Load conversations after login
    get().loadConversations();
    return user;
  },

  register: async (username, password) => {
    const res = await api.post('/auth/register/', { username, password });
    const { token, user } = res.data;
    localStorage.setItem('nepse_token', token);
    localStorage.setItem('nepse_user', JSON.stringify(user));
    set({ token, user });
    return user;
  },

  logout: async () => {
    try {
      await api.post('/auth/logout/');
    } catch {
      // ignore errors
    }
    localStorage.removeItem('nepse_token');
    localStorage.removeItem('nepse_user');
    set({
      user: null,
      token: null,
      conversations: [],
      activeConversationId: null,
      messages: [],
    });
  },

  // ── Conversation Actions ──────────────────────────

  loadConversations: async () => {
    try {
      const res = await api.get('/auth/conversations/');
      set({ conversations: res.data });
    } catch (err) {
      console.error('Failed to load conversations:', err);
    }
  },

  newConversation: () => {
    set({
      messages: [],
      activeConversationId: null,
    });
  },

  switchConversation: async (conversationId) => {
    try {
      const res = await api.get(`/auth/conversations/${conversationId}/`);
      const convo = res.data;
      // Map messages from API format to store format
      const messages = convo.messages.map((m, i) => ({
        id: m.id || Date.now() + i,
        role: m.role,
        content: m.content,
        isStreaming: false,
        signals: m.signals,
        citations: m.citations,
        toolsUsed: m.tools_used,
        routeUsed: m.route_used,
        llmProvider: m.llm_provider,
        tokenUsage: m.tokens_used || null,
        latencyMs: m.latency_ms,
        created_at: m.created_at,
      }));
      set({
        messages,
        activeConversationId: conversationId,
      });
    } catch (err) {
      console.error('Failed to load conversation:', err);
    }
  },

  deleteConversation: async (conversationId) => {
    try {
      await api.delete(`/auth/conversations/${conversationId}/`);
      const { activeConversationId } = get();
      set((s) => ({
        conversations: s.conversations.filter((c) => c.id !== conversationId),
        ...(activeConversationId === conversationId
          ? { messages: [], activeConversationId: null }
          : {}),
      }));
    } catch (err) {
      console.error('Failed to delete conversation:', err);
    }
  },
}));

export default useChatStore;
