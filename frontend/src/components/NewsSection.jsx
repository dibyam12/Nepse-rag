import { ExternalLink, AlertCircle } from 'lucide-react';

export default function NewsSection({ citations, symbol, content }) {
  const newsCitations = citations?.filter((c) => c.type === 'news') || [];
  
  // Detect if there's no news
  const noNewsMatch = content?.match(/no recent news/i) || content?.match(/no news available/i) || (citations && citations.length > 0 && newsCitations.length === 0 && content?.includes('News'));
  const hasNoNews = noNewsMatch && newsCitations.length === 0;

  if (newsCitations.length === 0 && !hasNoNews) return null;

  return (
    <div className="mt-8 mb-6 animate-fade-in">
      <div className="flex items-center gap-4 mb-4 opacity-70">
        <h3 className="text-xs font-semibold text-surface-500 dark:text-surface-400 m-0 tracking-widest uppercase">
          Latest News {symbol ? `— ${symbol}` : ''}
        </h3>
        <div className="flex-1 h-px bg-surface-200 dark:bg-surface-800" />
      </div>

      {hasNoNews ? (
        <div className="flex flex-col items-center justify-center p-6 bg-surface-50 dark:bg-surface-800/20 border border-surface-200 dark:border-surface-800 border-dashed rounded-xl text-center">
          <AlertCircle size={24} className="text-surface-400 dark:text-surface-500 mb-3" />
          <p className="text-sm text-surface-600 dark:text-surface-300 font-medium mb-1">
            No recent news was found for {symbol || 'this symbol'}.
          </p>
          <p className="text-xs text-surface-500 dark:text-surface-400 mb-4">
            The web search fallback chain did not return any articles in the past 7 days.
          </p>
          <div className="flex gap-3">
            <a href={`https://sharesansar.com/company/${symbol || ''}`} target="_blank" rel="noreferrer" className="text-[11px] font-medium text-brand-600 dark:text-brand-400 bg-brand-50 dark:bg-brand-500/10 px-3 py-1.5 rounded-full hover:bg-brand-100 dark:hover:bg-brand-500/20 transition-colors">
              Check ShareSansar
            </a>
            <a href={`https://merolagani.com/CompanyDetail.aspx?symbol=${symbol || ''}`} target="_blank" rel="noreferrer" className="text-[11px] font-medium text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-500/10 px-3 py-1.5 rounded-full hover:bg-blue-100 dark:hover:bg-blue-500/20 transition-colors">
              Check MeroLagani
            </a>
          </div>
        </div>
      ) : (
        <ul className="space-y-4 m-0 p-0 list-none">
          {newsCitations.map((news, idx) => (
            <li key={idx} className="flex gap-3 items-start group">
              <span className="w-1.5 h-1.5 rounded-full bg-brand-500 dark:bg-brand-400 mt-2 flex-shrink-0" />
              <div>
                <a href={news.url} target="_blank" rel="noreferrer" className="text-sm font-semibold text-surface-900 dark:text-surface-100 hover:text-brand-600 dark:hover:text-brand-400 transition-colors flex items-center gap-1.5 no-underline">
                  {news.headline}
                </a>
                <div className="flex items-center gap-2 mt-1">
                  <span className="text-[11px] text-brand-600 dark:text-brand-400">{news.url?.includes('sharesansar') ? 'ShareSansar' : news.url?.includes('merolagani') ? 'MeroLagani' : 'NepseAlpha'}</span>
                  <span className="text-[10px] text-surface-400 dark:text-surface-500">Recent</span>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
