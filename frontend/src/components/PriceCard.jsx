import useChatStore from '../store/chatStore';

export default function PriceCard({ symbol, signals }) {
  const { allSymbols } = useChatStore();

  if (!symbol || !signals || signals.close == null) return null;

  const stock = allSymbols.find((s) => s.symbol === symbol);
  const name = stock ? stock.name : symbol;
  const sector = stock ? stock.sector_name : 'N/A';

  const close = signals.close.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const volume = signals.volume ? signals.volume.toLocaleString() : 'N/A';
  const pctChange = signals.pct_change || 0;
  
  const isPositive = pctChange >= 0;
  const pctColor = isPositive ? 'text-emerald-500 bg-emerald-500/10 border-emerald-500/20' : 'text-red-500 bg-red-500/10 border-red-500/20';
  const pctIcon = isPositive ? '▲' : '▼';

  const dayRange = (signals.low && signals.high) 
    ? `${signals.low} - ${signals.high}`
    : 'N/A';
    
  // Mock 52W Range with "-"
  const range52w = '-';
  
  const vwap = signals.VWAP ? signals.VWAP.toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 2 }) : 'N/A';
  const ema20 = signals.EMA_20 ? signals.EMA_20.toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 2 }) : 'N/A';

  return (
    <div className="glass-card mb-6 border border-surface-200 dark:border-surface-700/50 rounded-xl overflow-hidden animate-fade-in">
      <div className="p-6">
        {/* Header */}
        <div className="flex justify-between items-start mb-4">
          <div>
            <h2 className="text-2xl font-bold text-surface-900 dark:text-surface-50 m-0 leading-tight tracking-tight">
              {symbol}
            </h2>
            <p className="text-surface-500 dark:text-surface-400 text-sm m-0 mt-0.5">
              {name}
            </p>
          </div>
          {sector !== 'N/A' && (
            <span className="px-3 py-1 bg-brand-500/10 text-brand-600 dark:text-brand-400 text-xs font-medium rounded-full border border-brand-500/20">
              {sector}
            </span>
          )}
        </div>

        {/* Price & Badge */}
        <div className="flex items-end gap-4 mb-8">
          <div className="flex items-baseline gap-1.5">
            <span className="text-surface-500 dark:text-surface-400 font-medium">NPR</span>
            <span className="text-4xl font-extrabold text-surface-900 dark:text-surface-50 tracking-tight">
              {close}
            </span>
          </div>
          <div className={`px-2.5 py-1 text-sm font-semibold rounded-md border flex items-center gap-1 ${pctColor}`}>
            <span className="text-[10px]">{pctIcon}</span>
            {Math.abs(pctChange)}%
          </div>
        </div>

        {/* 2x3 Grid Data */}
        <div className="grid grid-cols-3 gap-y-6 gap-x-4">
          <div>
            <p className="text-xs text-surface-500 dark:text-surface-400 mb-1">Volume</p>
            <p className="font-semibold text-surface-900 dark:text-surface-200">{volume}</p>
          </div>
          <div>
            <p className="text-xs text-surface-500 dark:text-surface-400 mb-1">Day Range</p>
            <p className="font-semibold text-surface-900 dark:text-surface-200">{dayRange}</p>
          </div>
          <div>
            <p className="text-xs text-surface-500 dark:text-surface-400 mb-1">52W Range</p>
            <p className="font-semibold text-surface-900 dark:text-surface-200">{range52w}</p>
          </div>
          
          <div>
            <p className="text-xs text-surface-500 dark:text-surface-400 mb-1">VWAP</p>
            <p className="font-semibold text-surface-900 dark:text-surface-200">{vwap}</p>
          </div>
          <div>
            <p className="text-xs text-surface-500 dark:text-surface-400 mb-1">EMA 20</p>
            <p className="font-semibold text-surface-900 dark:text-surface-200">{ema20}</p>
          </div>
          <div>
            <p className="text-xs text-surface-500 dark:text-surface-400 mb-1">Sector</p>
            <p className="font-semibold text-surface-900 dark:text-surface-200 truncate pr-2" title={sector}>{sector}</p>
          </div>
        </div>
      </div>
    </div>
  );
}
