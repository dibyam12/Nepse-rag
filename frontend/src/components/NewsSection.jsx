/**
 * NewsSection — Dot-list news layout with empty state.
 *
 * Matches the sample design: section title + dot + title + source/time meta.
 */
import { ExternalLink, AlertCircle, Clock } from 'lucide-react';

const cleanSnippet = (text) => text?.replace(/[#*_`]/g, '').slice(0, 120);

export default function NewsSection({ citations, symbol, content }) {
  const newsCitations = citations?.filter((c) => c.type === 'news') || [];

  const noNewsInContent =
    content?.match(/no recent news/i) ||
    content?.match(/no news available/i) ||
    content?.match(/news was found/i) ||
    content?.match(/did not return any articles/i);

  const hasNoNews = noNewsInContent && newsCitations.length === 0;

  if (newsCitations.length === 0 && !hasNoNews) return null;

  // Empty state
  if (hasNoNews) {
    return (
      <div className="news-empty">
        <AlertCircle size={16} className="news-empty-icon" />
        <div>
          <p className="news-empty-title">No recent news found for {symbol || 'this symbol'}</p>
          <p className="news-empty-sub">The web search returned no articles in the past 7 days.</p>
          <div className="news-links">
            <a href={`https://www.sharesansar.com/company/${symbol || ''}`}
               target="_blank" rel="noopener noreferrer" className="news-link">
              <ExternalLink size={12} /> ShareSansar
            </a>
            <a href={`https://merolagani.com/CompanyDetail.aspx?symbol=${symbol || ''}`}
               target="_blank" rel="noopener noreferrer" className="news-link">
              <ExternalLink size={12} /> MeroLagani
            </a>
            <a href={`https://nepsealpha.com/trading/1/history?symbol=${symbol || ''}`}
               target="_blank" rel="noopener noreferrer" className="news-link">
              <ExternalLink size={12} /> NepseAlpha
            </a>
          </div>
        </div>
      </div>
    );
  }

  // Derive section title from unique symbols in news citations
  const newsSymbols = [...new Set(newsCitations
    .map(c => c.symbol || symbol)
    .filter(Boolean)
  )];
  const sectionTitle = newsSymbols.length > 0
    ? `Latest News — ${newsSymbols.join(' & ')}`
    : `Latest News`;

  // Helper: clean up source labels (DDG fallback)
  function displaySource(article) {
    let src = article.source || '';
    if (!src || src.toLowerCase() === 'duckduckgo' || src === 'ddg') {
      // Extract domain from URL
      try {
        const url = new URL(article.url || '');
        src = url.hostname.replace(/^www\./, '');
      } catch { src = ''; }
    }
    return src;
  }

  // News list
  return (
    <div className="news-section">
      <div className="section-title">{sectionTitle}</div>
      {newsCitations.map((article, i) => (
        <a
          key={i}
          href={article.url || '#'}
          target="_blank"
          rel="noopener noreferrer"
          style={{ textDecoration: 'none', color: 'inherit' }}
        >
          <div className="news-item">
            <div className="news-dot" />
            <div className="news-content">
              <div className="news-title">{article.headline || 'No title'}</div>
              {(article.summary || article.excerpt || article.body || article.snippet) && (
                <div className="news-snippet">
                  {cleanSnippet(article.summary || article.excerpt || article.body || article.snippet)}
                </div>
              )}
              <div className="news-meta">
                {displaySource(article) && (
                  <span className="news-source-label">{displaySource(article)}</span>
                )}
                {article.published_at && (
                  <span style={{ display: 'flex', alignItems: 'center', gap: '3px' }}>
                    <Clock size={11} />
                    {new Date(article.published_at).toLocaleDateString('en-US', {
                      month: 'short', day: 'numeric', year: 'numeric',
                    })}
                  </span>
                )}
              </div>
            </div>
          </div>
        </a>
      ))}
    </div>
  );
}
