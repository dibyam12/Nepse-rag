/**
 * MessageBubble — Renders a single chat message.
 *
 * User messages: right-aligned teal bubble.
 * Assistant messages: avatar header + tool chips + structured content sections.
 */
import { TrendingUp } from 'lucide-react';
import LoadingIndicator from './LoadingIndicator';
import StatusIndicator from './StatusIndicator';
import SignalsTable from './SignalsTable';
import CitationList from './CitationList';
import PriceCard from './PriceCard';
import NewsSection from './NewsSection';

const TOOL_CHIP_CONFIG = {
  sql_tool:    { label: 'SQL',    cls: 'chip-sql' },
  graph_tool:  { label: 'Graph',  cls: 'chip-graph' },
  news_tool:   { label: 'News',   cls: 'chip-news' },
  vector_tool: { label: 'Vector', cls: 'chip-vector' },
};

const ROUTE_LABELS = {
  full_agent:  'Full Agent',
  sql_graph:   'SQL + Graph',
  vector_only: 'Vector',
  compare:     'Compare',
  chat:        'Chat',
};

function extractSymbol(signals, content) {
  if (signals?.symbol) return signals.symbol;
  const match = content?.match(/\b([A-Z]{2,6})\b/);
  return match ? match[1] : null;
}

function cleanContent(content) {
  if (!content) return '';
  return content
    .replace(/No recent news was found[^.]*\.\s*/gi, '')
    .replace(/The web search fallback chain[^.]*\.\s*/gi, '')
    .trim();
}

function extractThinking(content) {
  if (!content) return { thinkingText: '', cleanText: '' };
  
  const thinkingStartIdx = content.indexOf('<thinking>');
  const thinkingEndIdx = content.indexOf('</thinking>');
  
  let thinkingText = '';
  let cleanText = content;
  
  if (thinkingStartIdx !== -1) {
    if (thinkingEndIdx !== -1) {
      thinkingText = content.substring(thinkingStartIdx + 10, thinkingEndIdx).trim();
      cleanText = (content.substring(0, thinkingStartIdx) + content.substring(thinkingEndIdx + 11)).trim();
    } else {
      thinkingText = content.substring(thinkingStartIdx + 10).trim();
      cleanText = content.substring(0, thinkingStartIdx).trim();
    }
  }
  
  return { thinkingText, cleanText };
}

export default function MessageBubble({ message }) {
  const isUser = message.role === 'user';

  if (isUser) {
    return (
      <div className="message-user">
        <div className="bubble-user">{message.content}</div>
      </div>
    );
  }

  // ── Assistant bubble ──────────────────────────────────────────────
  const { content, signals, citations, toolsUsed, routeUsed,
    llmProvider, tokenUsage, latencyMs, isStreaming } = message;

  // Normalize signals: always work with an array
  const signalsList = Array.isArray(signals) ? signals : (signals ? [signals] : []);
  const primarySignals = signalsList[0] || null;

  const symbol = extractSymbol(primarySignals, content);
  
  const { thinkingText, cleanText } = extractThinking(content);
  const displayContent = cleanContent(cleanText);
  
  const hasThinking = content && content.includes('<thinking>');
  const isThinking = isStreaming && (
    !content ||
    (hasThinking && !content.includes('</thinking>'))
  );

  return (
    <div className="message-assistant">
      {/* Avatar + Name + Time */}
      <div className="msg-header">
        <div className="msg-avatar">
          <TrendingUp size={12} />
        </div>
        <span className="msg-name">NEPSE AI</span>
        {message.created_at && (
          <span className="msg-time">
            {new Date(message.created_at).toLocaleTimeString('en-US', {
              hour: '2-digit', minute: '2-digit',
            })}
          </span>
        )}
      </div>

      {/* Tool chips row */}
      {(toolsUsed || routeUsed) && (
        <div className="bubble-meta-row">
          {routeUsed && (
            <div className={`tool-chip chip-full`}>
              <span className="chip-dot" />
              {ROUTE_LABELS[routeUsed] || routeUsed}
            </div>
          )}
          {toolsUsed?.map((tool) => {
            const cfg = TOOL_CHIP_CONFIG[tool];
            return cfg ? (
              <div key={tool} className={`tool-chip ${cfg.cls}`}>
                <span className="chip-dot" />
                {cfg.label}
              </div>
            ) : null;
          })}
          {llmProvider && (
            <span className="provider-chip">via {llmProvider}</span>
          )}
          {latencyMs && (
            <span className="latency-chip">{(latencyMs / 1000).toFixed(1)}s</span>
          )}
        </div>
      )}

      <div className="bubble-assistant">
        {/* Loading state — show step timeline during streaming */}
        {isThinking && (
          <StatusIndicator
            statusMessage={message.statusMessage}
            steps={message.statusSteps}
          />
        )}

        {/* Price card(s) — one per symbol */}
        {signalsList.map((sig, idx) =>
          sig?.close != null ? (
            <PriceCard
              key={sig.symbol || idx}
              symbol={sig.symbol || symbol}
              signals={sig}
            />
          ) : null
        )}

        {/* Main LLM text */}
        {displayContent && (
          <div
            className="prose"
            dangerouslySetInnerHTML={{ __html: mdToHtml(displayContent) }}
          />
        )}

        {/* Technical indicators (show for all symbols in the list) */}
        {signalsList.map((sig, idx) => (
          sig && Object.keys(sig).length > 1 ? (
            <SignalsTable key={sig.symbol || idx} signals={sig} />
          ) : null
        ))}

        {/* News */}
        <NewsSection citations={citations} symbol={symbol} content={content} />

        {/* Sources / Citations */}
        {citations && citations.length > 0 && (
          <CitationList citations={citations} />
        )}
      </div>

      {/* Token usage */}
      {tokenUsage != null && (
        <div className="token-row">~{tokenUsage} tokens</div>
      )}
    </div>
  );
}

// ── Markdown → HTML ──────────────────────────────────────────────────────
function mdToHtml(text) {
  return text
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`(.+?)`/g, '<code>$1</code>')
    .replace(/^#{1,3}\s+(.+)$/gm, '<h3>$1</h3>')
    .replace(/^[-*]\s+(.+)$/gm, '<li>$1</li>')
    .replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>')
    .replace(/\n\n+/g, '</p><p>')
    .replace(/\n/g, '<br/>')
    .replace(/^(.+)$/, '<p>$1</p>');
}
