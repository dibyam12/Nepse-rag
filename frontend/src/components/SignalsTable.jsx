/**
 * SignalsTable — Card-grid of technical indicator values.
 *
 * Each indicator is a card with: label (muted), value (mono bold), status badge.
 * Matches the sample's indicator-grid design.
 */

export default function SignalsTable({ signals }) {
  if (!signals || Object.keys(signals).length === 0) return null;

  const cards = [];

  // RSI
  if (signals.RSI != null) {
    let statusText = 'Neutral', statusCls = 'status-neutral';
    if (signals.RSI >= 70) { statusText = 'Overbought'; statusCls = 'status-overbought'; }
    else if (signals.RSI > 55) { statusText = 'Bullish'; statusCls = 'status-bullish'; }
    else if (signals.RSI <= 30) { statusText = 'Oversold'; statusCls = 'status-bearish'; }
    else if (signals.RSI < 45) { statusText = 'Bearish'; statusCls = 'status-bearish'; }
    cards.push({ name: 'RSI (14)', value: signals.RSI.toFixed(1), statusText, statusCls });
  }

  // MACD
  if (signals.MACD != null) {
    const bull = signals.MACD > 0;
    cards.push({
      name: 'MACD',
      value: (bull ? '+' : '') + signals.MACD.toFixed(2),
      statusText: bull ? 'Bullish' : 'Bearish',
      statusCls: bull ? 'status-bullish' : 'status-bearish',
    });
  }

  // EMA 20
  if (signals.EMA_20 != null && signals.close != null) {
    const above = signals.close > signals.EMA_20;
    const diff = ((signals.close - signals.EMA_20) / signals.EMA_20 * 100).toFixed(1);
    cards.push({
      name: 'EMA 20',
      value: signals.EMA_20.toFixed(1),
      statusText: above ? `${diff}% Above` : `${diff}% Below`,
      statusCls: above ? 'status-bullish' : 'status-bearish',
    });
  }

  // BB Position
  if (signals.BB_upper != null && signals.BB_lower != null && signals.close != null) {
    const range = signals.BB_upper - signals.BB_lower;
    const pos = range !== 0 ? ((signals.close - signals.BB_lower) / range) * 100 : 50;
    let statusText = 'Mid Band', statusCls = 'status-neutral';
    if (pos >= 80) { statusText = 'Near Upper'; statusCls = 'status-overbought'; }
    else if (pos <= 20) { statusText = 'Near Lower'; statusCls = 'status-bearish'; }
    cards.push({ name: 'BB Position', value: `${pos.toFixed(0)}%`, statusText, statusCls });
  }

  // BB Upper
  if (signals.BB_upper != null) {
    cards.push({
      name: 'BB Upper', value: signals.BB_upper.toFixed(1),
      statusText: 'Resistance', statusCls: 'status-neutral',
    });
  }

  // BB Lower
  if (signals.BB_lower != null) {
    cards.push({
      name: 'BB Lower', value: signals.BB_lower.toFixed(1),
      statusText: 'Support', statusCls: 'status-neutral',
    });
  }

  // ATR
  if (signals.ATR != null) {
    cards.push({
      name: 'ATR', value: signals.ATR.toFixed(2),
      statusText: 'Volatility', statusCls: 'status-neutral',
    });
  }

  // OBV
  if (signals.OBV != null) {
    cards.push({
      name: 'OBV',
      value: Number(signals.OBV).toLocaleString('en-US', { notation: 'compact' }),
      statusText: 'Volume Flow', statusCls: 'status-neutral',
    });
  }

  if (cards.length === 0) return null;

  return (
    <div className="signals-section">
      <div className="section-title">Technical Indicators</div>
      <div className="signals-grid">
        {cards.map((card, i) => (
          <div key={i} className="signal-card">
            <div className="signal-name">{card.name}</div>
            <div className="signal-value">{card.value}</div>
            <span className={`signal-status ${card.statusCls}`}>{card.statusText}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
