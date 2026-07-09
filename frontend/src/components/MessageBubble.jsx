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

function MultiSignalsTable({ signalsList }) {
  return (
    <div className="table-wrapper">
      <table>
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Price</th>
            <th>Signal</th>
            <th>RSI</th>
            <th>MACD</th>
            <th>MFI</th>
          </tr>
        </thead>
        <tbody>
          {signalsList.map((sig, idx) => {
            const symbol = sig.symbol || 'N/A';
            const price = sig.close != null ? `NPR ${sig.close.toFixed(2)}` : 'N/A';
            const signalLabel = sig.signal_label || sig.Signal || 'Neutral';
            const rsi = sig.rsi != null ? sig.rsi.toFixed(1) : (sig.RSI != null ? sig.RSI.toFixed(1) : 'N/A');
            const macd = sig.macd != null ? sig.macd.toFixed(2) : (sig.MACD != null ? sig.MACD.toFixed(2) : 'N/A');
            const mfi = sig.mfi != null ? sig.mfi.toFixed(1) : (sig.MFI != null ? sig.MFI.toFixed(1) : 'N/A');
            return (
              <tr key={symbol || idx}>
                <td><strong>{symbol}</strong></td>
                <td>{price}</td>
                <td>{signalLabel}</td>
                <td>{rsi}</td>
                <td>{macd}</td>
                <td>{mfi}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
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

                {/* Multi-stock: show table directly below the answer */}
                {signalsList.length > 1 && <MultiSignalsTable signalsList={signalsList} />}

                {/* Current market data — collapsed by default (only for single symbol) */}
                {signalsList.length === 1 && hasPriceCards && (
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
                {/* Price card(s) or MultiSignalsTable */}
                {signalsList.length > 1 ? (
                  <MultiSignalsTable signalsList={signalsList} />
                ) : (
                  signalsList.map((sig, idx) =>
                    sig?.close != null ? (
                      <PriceCard
                        key={sig.symbol || idx}
                        symbol={sig.symbol || symbol}
                        signals={sig}
                      />
                    ) : null
                  )
                )}

                {/* Main LLM text */}
                {displayContent && (
                  <div
                    className="prose"
                    dangerouslySetInnerHTML={{ __html: mdToHtml(displayContent) }}
                  />
                )}

                {/* Technical indicators (only show for single symbol in the list) */}
                {signalsList.length === 1 && signalsList.map((sig, idx) => (
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

  // 1. Markdown Table Parser (GFM syntax: | Symbol | Price |)
  html = html.replace(/((?:^\|.+$\n?)+)/gm, (block) => {
    const lines = block.trim().split('\n');
    if (lines.length < 2) return block;

    const isSeparator = /^\|(?:\s*:?-+:?\s*\|)+$/.test(lines[1].trim());
    if (!isSeparator) return block;

    const headers = lines[0]
      .split('|')
      .slice(1, -1)
      .map(h => h.trim());

    const rows = lines.slice(2).map(line => {
      return line
        .split('|')
        .slice(1, -1)
        .map(cell => cell.trim());
    });

    const thead = `<thead><tr>${headers.map(h => `<th>${h}</th>`).join('')}</tr></thead>`;
    const tbody = `<tbody>${rows.map(row => `<tr>${row.map(cell => `<td>${cell}</td>`).join('')}</tr>`).join('')}</tbody>`;

    return `<div class="table-wrapper"><table>${thead}${tbody}</table></div>`;
  });

  // 2. Generic List-to-Table Fallback (Issue 4 & 8 structural fallback)
  const mdLines = html.split('\n');
  const processedLines = [];
  let currentTableRows = [];

  const isStockListLine = (lineStr) => {
    const clean = lineStr.trim();
    if (!clean) return false;
    if (!/^(?:[-*+]|\d+\.)\s+/.test(clean)) return false;
    if (!/\b[A-Z]{2,6}\b/.test(clean)) return false;
    return /\b(?:rsi|macd|mfi|price|close|signal|🟢|🟡|🔴)\b/i.test(clean);
  };

  const renderTableFromRows = (rows) => {
    if (rows.length === 0) return '';
    const maxCols = Math.max(...rows.map(r => r.length));
    let headers = ['Symbol', 'Price', 'Signal', 'RSI', 'MACD', 'MFI'];
    if (maxCols < headers.length) {
      headers = headers.slice(0, maxCols);
    }
    const thead = `<thead><tr>${headers.map(h => `<th>${h}</th>`).join('')}</tr></thead>`;
    const tbody = `<tbody>${rows.map(row => {
      while (row.length < headers.length) row.push('');
      return `<tr>${row.map(cell => `<td>${cell}</td>`).join('')}</tr>`;
    }).join('')}</tbody>`;
    return `<div class="table-wrapper"><table>${thead}${tbody}</table></div>`;
  };

  for (let i = 0; i < mdLines.length; i++) {
    const line = mdLines[i];
    if (isStockListLine(line)) {
      const cleanLine = line.replace(/^(?:[-*+]|\d+\.)\s+/, '').trim();
      let parts = [];
      if (cleanLine.includes('|')) {
        parts = cleanLine.split(/\s*\|\s*/);
      } else if (cleanLine.includes('—')) {
        parts = cleanLine.split(/\s*—\s*/);
      } else if (cleanLine.includes(' - ')) {
        parts = cleanLine.split(/\s+-\s+/);
      } else {
        const parenMatch = cleanLine.match(/\(([^)]+)\)/);
        if (parenMatch) {
          const symPart = cleanLine.replace(/\([^)]+\)/, '').trim();
          const inner = parenMatch[1].split(/\s*,\s*/);
          parts = [symPart, ...inner];
        } else {
          parts = cleanLine.split(/\s*,\s*/);
        }
      }
      currentTableRows.push(parts.map(p => p.trim()));
    } else {
      if (line.trim() === '' && currentTableRows.length > 0 && i + 1 < mdLines.length && isStockListLine(mdLines[i + 1])) {
        continue;
      }
      if (currentTableRows.length > 0) {
        processedLines.push(renderTableFromRows(currentTableRows));
        currentTableRows = [];
      }
      processedLines.push(line);
    }
  }
  if (currentTableRows.length > 0) {
    processedLines.push(renderTableFromRows(currentTableRows));
  }
  html = processedLines.join('\n');

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

