/**
 * PriceCard — Premium stock price display card.
 *
 * Layout: Symbol + Name | Sector pill
 *         NPR + Large price + Change pill + Sparkline Trend Chart
 *         3-column meta grid (Volume, Day Range, 52W, VWAP, EMA20, Sector)
 */
import { ChevronUp, ChevronDown } from 'lucide-react';
import useChatStore from '../store/chatStore';

function Sparkline({ prices, isPositive }) {
  if (!prices || prices.length < 2) return null;

  const min = Math.min(...prices);
  const max = Math.max(...prices);
  const range = max - min || 1;

  const width = 90;
  const height = 30;
  const padding = 2;

  const points = prices.map((price, index) => {
    const x = padding + (index / (prices.length - 1)) * (width - padding * 2);
    // Invert Y since SVG y=0 is top
    const y = padding + (1 - (price - min) / range) * (height - padding * 2);
    return `${x},${y}`;
  });

  const pathD = `M ${points.join(' L ')}`;
  const strokeColor = isPositive ? 'var(--chat-success, #10b981)' : 'var(--chat-error, #ef4444)';
  const gradientId = `sparkline-grad-${Math.random().toString(36).substr(2, 9)}`;

  return (
    <div className="price-sparkline" style={{ display: 'flex', alignItems: 'center', marginLeft: '12px' }}>
      <svg width={width} height={height}>
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={strokeColor} stopOpacity="0.15" />
            <stop offset="100%" stopColor={strokeColor} stopOpacity="0.0" />
          </linearGradient>
        </defs>
        {/* Fill under the line */}
        <path
          d={`${pathD} L ${width - padding},${height} L ${padding},${height} Z`}
          fill={`url(#${gradientId})`}
        />
        {/* Stroke line */}
        <path
          d={pathD}
          fill="none"
          stroke={strokeColor}
          strokeWidth="1.75"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </div>
  );
}

export default function PriceCard({ symbol, signals }) {
  const store = useChatStore();
  const symbolsList = store.allSymbols || store.symbols || [];

  if (!symbol || !signals || signals.close == null) return null;

  const stock = symbolsList.find((s) => s.symbol === symbol);
  const name = signals.name || stock?.name || symbol;
  const sector = signals.sector || stock?.sector_name || 'N/A';

  const close = signals.close;
  const pctChange = signals.pct_change ?? 0;
  const isPositive = pctChange > 0;
  const isNegative = pctChange < 0;

  const fmt = (v, dec = 2) =>
    v != null
      ? Number(v).toLocaleString('en-US', { minimumFractionDigits: dec, maximumFractionDigits: dec })
      : '—';

  return (
    <div className="price-card">
      {/* Header: symbol + sector */}
      <div className="price-card-header">
        <div>
          <div className="price-card-symbol">{symbol}</div>
          <div className="price-card-name">{name}</div>
        </div>
        <span className="price-sector-pill">{sector}</span>
      </div>

      {/* Price + change + sparkline wrapper */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
        <div className="price-main-row" style={{ marginBottom: 0 }}>
          <span className="price-currency">NPR</span>
          <span className="price-value">{fmt(close)}</span>
          <span className={`price-change-pill ${isPositive ? 'change-up' : isNegative ? 'change-down' : 'change-neutral'}`}>
            {isPositive ? <ChevronUp size={14} /> : isNegative ? <ChevronDown size={14} /> : null}
            {isPositive ? '+' : ''}{pctChange.toFixed(2)}%
          </span>
        </div>
        <Sparkline prices={signals.recent_prices} isPositive={isPositive} />
      </div>

      {/* Meta grid */}
      <div className="price-meta-grid">
        <MetaItem label="Volume" value={signals.volume ? Number(signals.volume).toLocaleString() : '—'} />
        <MetaItem
          label="Day Range"
          value={signals.low != null && signals.high != null ? `${fmt(signals.low)} – ${fmt(signals.high)}` : '—'}
        />
        <MetaItem
          label="52W Range"
          value={signals.week52_low != null && signals.week52_high != null ? `${fmt(signals.week52_low)} – ${fmt(signals.week52_high)}` : '—'}
        />
        <MetaItem label="VWAP" value={signals.VWAP != null ? fmt(signals.VWAP, 1) : '—'} />
        <MetaItem label="EMA 20" value={signals.EMA_20 != null ? fmt(signals.EMA_20, 1) : '—'} />
        <MetaItem label="Sector" value={sector} />
      </div>

      {/* Data date */}
      {signals.date && (
        <div className="price-card-date">Data as of {signals.date}</div>
      )}
    </div>
  );
}

function MetaItem({ label, value }) {
  return (
    <div className="price-meta-item">
      <div className="price-meta-label">{label}</div>
      <div className="price-meta-value">{value}</div>
    </div>
  );
}
