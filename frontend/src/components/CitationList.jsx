/**
 * CitationList — Source chips section.
 *
 * Horizontal chip list with type-colored icons (DB, Graph, Doc, Web).
 * Matches the sample's sources-section design.
 */
import { Database, GitBranch, FileText, Globe, ExternalLink } from 'lucide-react';

const CITATION_CONFIG = {
  db: {
    icon: Database,
    colorClass: 'source-type-db',
    label: (c) => `DB: ${c.symbol || ''} ${c.date || ''}`.trim(),
  },
  news: {
    icon: Globe,
    colorClass: 'source-type-web',
    label: (c) => c.headline ? c.headline.slice(0, 50) + (c.headline.length > 50 ? '…' : '') : 'Web',
  },
  vector: {
    icon: FileText,
    colorClass: 'source-type-doc',
    label: (c) => c.source_file || 'Document',
  },
  doc: {
    icon: FileText,
    colorClass: 'source-type-doc',
    label: (c) => {
      let text = c.file || c.source_file || 'Document';
      if (c.section) text += ` §${c.section}`;
      return text;
    },
  },
  graph: {
    icon: GitBranch,
    colorClass: 'source-type-graph',
    label: (c) => c.description || 'Graph',
  },
};

export default function CitationList({ citations }) {
  if (!citations || citations.length === 0) return null;

  return (
    <div className="sources-section">
      <div className="section-title">Sources</div>
      <div className="sources-list">
        {citations.map((citation, i) => {
          const type = citation.type || 'doc';
          const config = CITATION_CONFIG[type] || CITATION_CONFIG.doc;
          const Icon = config.icon;
          const label = config.label(citation);
          const isClickable = type === 'news' && citation.url;

          const chipContent = (
            <div className="source-chip" key={i}>
              <Icon size={12} className={config.colorClass} />
              <span>{label}</span>
              {isClickable && <ExternalLink size={10} style={{ opacity: 0.6 }} />}
            </div>
          );

          if (isClickable) {
            return (
              <a key={i} href={citation.url} target="_blank" rel="noopener noreferrer"
                 style={{ textDecoration: 'none', color: 'inherit' }}>
                {chipContent}
              </a>
            );
          }

          return chipContent;
        })}
      </div>
    </div>
  );
}
