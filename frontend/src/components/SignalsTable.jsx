/**
 * SignalsTable — Renders technical indicator signals in a clean grid.
 *
 * Shows RSI, MACD, EMA, Bollinger Bands.
 * Color-codes status: overbought/oversold for RSI, bullish/bearish for MACD.
 */
export default function SignalsTable({ signals }) {
  if (!signals || Object.keys(signals).length === 0) return null;

  const cards = [];

  // RSI
  if (signals.RSI != null) {
    let statusText = 'Neutral';
    let statusClass = 'badge-gray';
    if (signals.RSI > 70) {
      statusText = 'Overbought';
      statusClass = 'badge-red';
    } else if (signals.RSI < 30) {
      statusText = 'Oversold';
      statusClass = 'badge-green';
    }
    cards.push({ name: 'RSI (14)', value: signals.RSI.toFixed(1), status: statusText, statusClass });
  }

  // MACD
  if (signals.MACD != null) {
    const isBullish = signals.MACD > 0;
    cards.push({
      name: 'MACD',
      value: signals.MACD > 0 ? `+${signals.MACD.toFixed(2)}` : signals.MACD.toFixed(2),
      status: isBullish ? 'Bullish' : 'Bearish',
      statusClass: isBullish ? 'badge-green' : 'badge-red',
    });
  }

  // EMA 20
  if (signals.EMA_20 != null && signals.close != null) {
    const isAbove = signals.close > signals.EMA_20;
    cards.push({
      name: 'EMA 20',
      value: signals.EMA_20.toFixed(1),
      status: isAbove ? 'Above' : 'Below',
      statusClass: 'badge-gray',
    });
  }

  // BB Position
  if (signals.BB_upper != null && signals.BB_lower != null && signals.close != null) {
    const range = signals.BB_upper - signals.BB_lower;
    // protect against div by zero
    const pos = range !== 0 ? ((signals.close - signals.BB_lower) / range) * 100 : 50;
    let statusText = 'Mid Band';
    if (pos >= 80) statusText = 'Overbought';
    else if (pos <= 20) statusText = 'Oversold';
    
    cards.push({
      name: 'BB Position',
      value: `${pos.toFixed(0)}%`,
      status: statusText,
      statusClass: 'badge-gray',
    });
  }

  // BB Upper
  if (signals.BB_upper != null) {
    cards.push({
      name: 'BB Upper',
      value: signals.BB_upper.toFixed(1),
      status: 'Resistance',
      statusClass: 'badge-gray',
    });
  }

  // BB Lower
  if (signals.BB_lower != null) {
    cards.push({
      name: 'BB Lower',
      value: signals.BB_lower.toFixed(1),
      status: 'Support',
      statusClass: 'badge-gray',
    });
  }

  if (cards.length === 0) return null;

  return (
    <div className="mt-6 mb-8 animate-fade-in">
      <div className="flex items-center gap-4 mb-4 opacity-70">
        <h3 className="text-xs font-semibold text-surface-500 dark:text-surface-400 m-0 tracking-widest uppercase">
          Technical Indicators
        </h3>
        <div className="flex-1 h-px bg-surface-200 dark:bg-surface-800" />
      </div>
      
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        {cards.map((c, i) => (
          <div key={i} className="flex flex-col p-3 rounded-lg border border-surface-200 dark:border-surface-700/50 bg-surface-50/50 dark:bg-surface-800/30">
            <span className="text-xs text-surface-500 dark:text-surface-400 mb-1">{c.name}</span>
            <span className="text-base font-bold text-surface-900 dark:text-surface-50 mb-2">{c.value}</span>
            <div className="mt-auto">
              <span className={`badge ${c.statusClass} text-[9px] px-1.5 py-0.5 inline-flex`}>
                {c.status}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
