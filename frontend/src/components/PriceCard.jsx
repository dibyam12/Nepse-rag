/**
 * PriceCard — Premium stock price display card.
 *
 * Layout: Symbol + Name | Sector pill
 *         NPR + Large price + Change pill
 *         3-column meta grid (Volume, Day Range, 52W, VWAP, EMA20, Sector)
 */
import { ChevronUp, ChevronDown } from 'lucide-react';
import useChatStore from '../store/chatStore';

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

      {/* Price + change */}
      <div className="price-main-row">
        <span className="price-currency">NPR</span>
        <span className="price-value">{fmt(close)}</span>
        <span className={`price-change-pill ${isPositive ? 'change-up' : isNegative ? 'change-down' : 'change-neutral'}`}>
          {isPositive ? <ChevronUp size={14} /> : isNegative ? <ChevronDown size={14} /> : null}
          {isPositive ? '+' : ''}{pctChange.toFixed(2)}%
        </span>
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
