/**
 * MessageBubble — Renders a single chat message.
 *
 * User messages: right-aligned teal bubble.
 * Assistant messages: avatar header + tool chips + structured content sections.
 */
import { useState, useEffect } from 'react';
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

export default function MessageBubble({ message, userQuestion }) {
  const isUser = message.role === 'user';

  const [showStreamingContent, setShowStreamingContent] = useState(!message.isStreaming);
  const [showCurrentData, setShowCurrentData] = useState(false);

  useEffect(() => {
    if (!message.isStreaming) {
      setShowStreamingContent(true);
      return;
    }

    if (message.isStreaming && !showStreamingContent) {
      const timer = setTimeout(() => {
        setShowStreamingContent(true);
      }, 300);
      return () => clearTimeout(timer);
    }
  }, [message.isStreaming, showStreamingContent]);

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

  // ── Answer-focus heuristic ─────────────────────────────────────
  // When the user is asking a follow-up / historical / educational question,
  // the LLM answer is the primary content. The PriceCard (current market data)
  // becomes secondary context and is shown collapsed below the answer.
  const ANSWER_FOCUS_ROUTES = ['vector_only', 'chat'];
  const ANSWER_FOCUS_PATTERNS = /\b(year|ago|histor|was|used\s+to|changed|compare|difference|when|why|explain|what\s+is|how|before|previous|last\s+year|2\d{3})\b/i;

  const isAnswerFocused = !isStreaming && displayContent && (
    ANSWER_FOCUS_ROUTES.includes(routeUsed) ||
    (userQuestion && ANSWER_FOCUS_PATTERNS.test(userQuestion))
  );

  const hasPriceCards = signalsList.some(sig => sig?.close != null);

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
        {!showStreamingContent ? (
          <LoadingIndicator />
        ) : (
          <>
            {/* Loading state — show step timeline during streaming */}
            {isThinking && (
              <StatusIndicator
                statusMessage={message.statusMessage}
                steps={message.statusSteps}
              />
            )}

            {isAnswerFocused ? (
              /* ── ANSWER-FOCUS MODE: LLM answer first, PriceCard secondary ── */
              <>
                {/* Highlighted primary answer */}
                {displayContent && (
                  <div
                    className="prose answer-highlight"
                    dangerouslySetInnerHTML={{ __html: mdToHtml(displayContent) }}
                  />
                )}

                {/* Current market data — collapsed by default */}
                {hasPriceCards && (
                  <div className="current-data-section">
                    <button
                      className="current-data-toggle"
                      onClick={() => setShowCurrentData(v => !v)}
                      aria-expanded={showCurrentData}
                    >
                      <span className="toggle-icon">{showCurrentData ? '▾' : '▸'}</span>
                      Current Market Data
                    </button>
                    {showCurrentData && (
                      <div className="current-data-body">
                        {signalsList.map((sig, idx) =>
                          sig?.close != null ? (
                            <PriceCard
                              key={sig.symbol || idx}
                              symbol={sig.symbol || symbol}
                              signals={sig}
                            />
                          ) : null
                        )}
                        {signalsList.map((sig, idx) => (
                          sig && Object.keys(sig).length > 1 ? (
                            <SignalsTable key={sig.symbol || idx} signals={sig} />
                          ) : null
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </>
            ) : (
              /* ── DEFAULT MODE: PriceCard first, then LLM answer ── */
              <>
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
              </>
            )}

            {/* News */}
            <NewsSection citations={citations} symbol={symbol} content={content} />

            {/* Sources / Citations */}
            {citations && citations.length > 0 && (
              <CitationList citations={citations} />
            )}
          </>
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
  if (!text) return '';

  // Escape HTML special chars first
  let html = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

  // Inline: bold, italic, code
  html = html
    .replace(/\*\*(.+?)\*\*/gs, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/gs,     '<em>$1</em>')
    .replace(/`([^`]+)`/g,      '<code>$1</code>');

  // Headings (h1–h4)
  html = html
    .replace(/^####\s+(.+)$/gm, '<h4>$1</h4>')
    .replace(/^###\s+(.+)$/gm,  '<h3>$1</h3>')
    .replace(/^##\s+(.+)$/gm,   '<h3>$1</h3>')
    .replace(/^#\s+(.+)$/gm,    '<h3>$1</h3>');

  // Horizontal rule
  html = html.replace(/^[-*]{3,}$/gm, '<hr/>');

  // Ordered list items: "1. text" → <li>text</li> wrapped in <ol>
  html = html.replace(/((?:^\d+\.\s+.+$\n?)+)/gm, (block) => {
    const items = block
      .trim()
      .split('\n')
      .map(line => line.replace(/^\d+\.\s+/, '').trim())
      .filter(Boolean)
      .map(line => `<li>${line}</li>`)
      .join('');
    return `<ol>${items}</ol>`;
  });

  // Unordered list items: "- text" or "* text" → <li> wrapped in <ul>
  html = html.replace(/((?:^[-*]\s+.+$\n?)+)/gm, (block) => {
    const items = block
      .trim()
      .split('\n')
      .map(line => line.replace(/^[-*]\s+/, '').trim())
      .filter(Boolean)
      .map(line => `<li>${line}</li>`)
      .join('');
    return `<ul>${items}</ul>`;
  });

  // Paragraphs: double newlines
  html = html
    .replace(/\n\n+/g, '</p><p>')
    .replace(/\n/g,    '<br/>');

  // Wrap in <p> if not already wrapped in a block element
  if (!/^<(h[1-4]|ul|ol|hr|p)/.test(html.trim())) {
    html = `<p>${html}</p>`;
  }

  return html;
}

