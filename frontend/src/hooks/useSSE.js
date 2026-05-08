/**
 * SSE streaming hook.
 *
 * Note: The main SSE logic is embedded in chatStore.sendMessage().
 * This hook provides a standalone streaming function for advanced usage.
 */
import useChatStore from '../store/chatStore';

export function useSSE() {
  const { appendToken, finalizeMessage } = useChatStore();

  const streamQuery = (question, symbol, messageId) => {
    const params = new URLSearchParams({ question });
    if (symbol) params.append('symbol', symbol);

    const token = localStorage.getItem('nepse_token');
    if (token) params.append('token', token);

    const url = `/api/query/stream/?${params.toString()}`;
    const eventSource = new EventSource(url);

    let signals = null;
    let citations = null;
    let routeUsed = null;
    let toolsUsed = null;
    let llmProvider = null;
    let latencyMs = null;

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        switch (data.type) {
          case 'token':
            appendToken(messageId, data.content);
            break;
          case 'signals':
            signals = data.data;
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
            break;
          case 'done':
            latencyMs = data.latency_ms;
            finalizeMessage(messageId, {
              signals, citations, routeUsed,
              toolsUsed, llmProvider, latencyMs,
            });
            eventSource.close();
            break;
          case 'error':
            appendToken(messageId, data.message || 'Error occurred.');
            finalizeMessage(messageId, {});
            eventSource.close();
            break;
        }
      } catch (e) {
        console.error('SSE parse error:', e);
      }
    };

    eventSource.onerror = () => {
      eventSource.close();
    };

    return eventSource;
  };

  return { streamQuery };
}
