/**
 * MessageBubble — Renders a single chat message.
 *
 * User: right-aligned indigo gradient.
 * Assistant: left-aligned glass card with tool badges, signals table, citations.
 */
import LoadingIndicator from './LoadingIndicator';
import SignalsTable from './SignalsTable';
import CitationList from './CitationList';
import PriceCard from './PriceCard';
import NewsSection from './NewsSection';

const TOOL_BADGES = {
  sql_tool:    { label: 'SQL',    className: 'badge-blue' },
  graph_tool:  { label: 'Graph',  className: 'badge-green' },
  news_tool:   { label: 'News',   className: 'badge-orange' },
  vector_tool: { label: 'Vector', className: 'badge-purple' },
};

const ROUTE_LABELS = {
  full_agent:  'Full Agent',
  sql_graph:   'SQL + Graph',
  vector_only: 'Vector',
  compare:     'Compare',
};

export default function MessageBubble({ message }) {
  const isUser = message.role === 'user';

  if (isUser) {
    return (
      <div className="flex justify-end mb-4 animate-fade-in">
        <div className="max-w-[75%] lg:max-w-[60%]">
          <div className="px-4 py-3 rounded-2xl rounded-tr-md
                          bg-gradient-to-br from-brand-500 to-brand-600
                          text-white shadow-md">
            <p className="whitespace-pre-wrap text-sm leading-relaxed">
              {message.content}
            </p>
          </div>
        </div>
      </div>
    );
  }

  // Assistant message
  const isEmpty = !message.content && message.isStreaming;

  // Extract symbol from citations to pass to PriceCard
  const symbol = message.citations?.find(c => c.type === 'db' || c.symbol)?.symbol || 
                 message.citations?.find(c => c.type === 'news' && c.headline)?.headline?.split(' ')[0] || 
                 '';

  // Filter content
  let displayContent = message.content || '';
  if (displayContent.match(/no recent news/i) || displayContent.match(/no news available/i)) {
    displayContent = displayContent.replace(/.*no recent news.*/ig, '').replace(/.*no news available.*/ig, '');
  }
  
  // Hide repetitive text if signals are present (heuristic for clean UI)
  if (message.signals) {
    displayContent = displayContent
      .replace(/.*Close price of.*/ig, '')
      .replace(/.*Price:.*NPR.*/ig, '')
      .replace(/.*Volume:.*/ig, '')
      .replace(/.*RSI:.*/ig, '')
      .replace(/.*MACD:.*/ig, '')
      .replace(/.*EMA-20:.*/ig, '')
      .replace(/.*Bollinger:.*/ig, '')
      .replace(/.*Technical Indicators:.*/ig, '');
  }

  return (
    <div className="flex justify-start mb-4 animate-fade-in">
      <div className="max-w-[85%] lg:max-w-[75%]">
        {/* Tool + Route badges */}
        {(message.toolsUsed || message.routeUsed) && !message.isStreaming && (
          <div className="flex flex-wrap items-center gap-1.5 mb-2">
            {message.routeUsed && (
              <span className="badge badge-gray text-[10px]">
                {ROUTE_LABELS[message.routeUsed] || message.routeUsed}
              </span>
            )}
            {message.toolsUsed?.map((tool) => {
              const config = TOOL_BADGES[tool] || { label: tool, className: 'badge-gray' };
              return (
                <span key={tool} className={`badge ${config.className} text-[10px]`}>
                  {config.label}
                </span>
              );
            })}
            {message.llmProvider && (
              <span className="badge badge-gray text-[10px]">
                via {message.llmProvider}
              </span>
            )}
            {message.latencyMs && (
              <span className="badge badge-gray text-[10px]">
                {message.latencyMs}ms
              </span>
            )}
          </div>
        )}

        {/* Message body */}
        <div className="glass-card px-5 py-4">
          {isEmpty ? (
            <LoadingIndicator />
          ) : (
            <div>
              {/* Price Card */}
              {message.signals && <PriceCard symbol={symbol} signals={message.signals} />}

              {/* Signals Grid */}
              {message.signals && <SignalsTable signals={message.signals} />}

              {/* News Section */}
              <NewsSection citations={message.citations} symbol={symbol} content={message.content} />

              {/* Text Content */}
              {displayContent.trim() && (
                <p className={`whitespace-pre-wrap text-sm leading-relaxed 
                             text-surface-800 dark:text-surface-200 mt-4
                             ${message.isStreaming ? 'typing-cursor' : ''}`}>
                  {displayContent.trim()}
                </p>
              )}

              {/* Citations */}
              {message.citations && <CitationList citations={message.citations} />}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
