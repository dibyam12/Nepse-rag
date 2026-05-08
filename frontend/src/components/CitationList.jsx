/**
 * CitationList — Horizontal scrollable list of citation chips.
 *
 * Types: db (gray), news (blue, clickable), doc/vector (green), graph (purple).
 */
import { Database, Newspaper, FileText, GitBranch, ExternalLink } from 'lucide-react';

const CITATION_CONFIG = {
  db: {
    icon: Database,
    className: 'badge-gray',
    label: (c) => `DB: ${c.symbol || ''} ${c.date || ''}`.trim(),
  },
  news: {
    icon: Newspaper,
    className: 'badge-blue',
    label: (c) => c.headline ? c.headline.slice(0, 50) + (c.headline.length > 50 ? '…' : '') : 'News',
  },
  vector: {
    icon: FileText,
    className: 'badge-green',
    label: (c) => c.source_file || 'Document',
  },
  doc: {
    icon: FileText,
    className: 'badge-green',
    label: (c) => {
      let text = c.file || c.source_file || 'Document';
      if (c.section) text += ` §${c.section}`;
      return text;
    },
  },
  graph: {
    icon: GitBranch,
    className: 'badge-purple',
    label: (c) => c.description || 'Graph',
  },
};

export default function CitationList({ citations }) {
  if (!citations || citations.length === 0) return null;

  return (
    <div className="mt-8 mb-2 animate-fade-in">
      <div className="flex items-center gap-4 mb-3 opacity-70">
        <h3 className="text-xs font-semibold text-surface-500 dark:text-surface-400 m-0 tracking-widest uppercase">
          Sources
        </h3>
        <div className="flex-1 h-px bg-surface-200 dark:bg-surface-800" />
      </div>
      <div className="flex flex-wrap gap-2.5">
        {citations.map((citation, i) => {
          const type = citation.type || 'doc';
          const config = CITATION_CONFIG[type] || CITATION_CONFIG.doc;
          const Icon = config.icon;
          const label = config.label(citation);
          const isClickable = type === 'news' && citation.url;

          const chip = (
            <span
              key={i}
              className={`flex items-center gap-2 px-3 py-1.5 rounded-full border border-surface-200 dark:border-surface-700 bg-surface-50 dark:bg-surface-800/50 text-xs text-surface-700 dark:text-surface-300
                         ${isClickable ? 'cursor-pointer hover:bg-surface-100 dark:hover:bg-surface-700 transition-colors' : ''}
                         `}
              title={type === 'news' ? citation.url : label}
            >
              <Icon size={12} className={`flex-shrink-0 ${config.className.includes('blue') ? 'text-blue-500' : config.className.includes('green') ? 'text-emerald-500' : config.className.includes('purple') ? 'text-purple-500' : 'text-surface-500'}`} />
              <span className="truncate max-w-[250px] font-medium">{label}</span>
              {isClickable && <ExternalLink size={10} className="flex-shrink-0 opacity-60 ml-1" />}
            </span>
          );

          if (isClickable) {
            return (
              <a
                key={i}
                href={citation.url}
                target="_blank"
                rel="noopener noreferrer"
                className="no-underline"
              >
                {chip}
              </a>
            );
          }

          return chip;
        })}
      </div>
    </div>
  );
}
