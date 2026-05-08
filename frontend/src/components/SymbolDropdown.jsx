/**
 * SymbolDropdown — Searchable stock symbol selector.
 *
 * Loads from /api/symbols/ via parent store.
 * Shows SYMBOL — Sector Name in dropdown options.
 */
import { useState, useRef, useEffect } from 'react';
import { ChevronDown, Search, X } from 'lucide-react';
import useChatStore from '../store/chatStore';

export default function SymbolDropdown() {
  const { symbols, selectedSymbol, setSymbol } = useChatStore();
  const [isOpen, setIsOpen] = useState(false);
  const [filter, setFilter] = useState('');
  const dropdownRef = useRef(null);
  const inputRef = useRef(null);

  // Close on outside click
  useEffect(() => {
    const handler = (e) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  // Focus input when dropdown opens
  useEffect(() => {
    if (isOpen && inputRef.current) {
      inputRef.current.focus();
    }
  }, [isOpen]);

  const filtered = symbols.filter((s) => {
    const q = filter.toLowerCase();
    return (
      s.symbol.toLowerCase().includes(q) ||
      (s.name || '').toLowerCase().includes(q) ||
      (s.sector_name || '').toLowerCase().includes(q)
    );
  });

  const handleSelect = (symbol) => {
    setSymbol(symbol);
    setFilter('');
    setIsOpen(false);
  };

  const handleClear = (e) => {
    e.stopPropagation();
    setSymbol('');
    setFilter('');
  };

  return (
    <div ref={dropdownRef} className="relative">
      {/* Trigger button */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-2 px-3 h-[46px] rounded-xl
                   bg-surface-100 dark:bg-surface-800
                   border border-surface-200 dark:border-surface-700
                   hover:border-brand-400 dark:hover:border-brand-500
                   text-sm font-medium transition-all duration-200
                   min-w-[120px] whitespace-nowrap"
        id="symbol-dropdown-trigger"
      >
        <span className={`truncate ${selectedSymbol
          ? 'text-brand-600 dark:text-brand-400'
          : 'text-surface-400 dark:text-surface-500'
        }`}>
          {selectedSymbol || 'Symbol'}
        </span>
        {selectedSymbol ? (
          <X
            size={14}
            className="text-surface-400 hover:text-surface-600 ml-auto flex-shrink-0"
            onClick={handleClear}
          />
        ) : (
          <ChevronDown size={14} className="text-surface-400 ml-auto flex-shrink-0" />
        )}
      </button>

      {/* Dropdown panel */}
      {isOpen && (
        <div className="absolute bottom-full mb-2 left-0 z-50 w-72
                        glass-card overflow-hidden animate-slide-in-up">
          {/* Search input */}
          <div className="p-2 border-b border-surface-200 dark:border-surface-700">
            <div className="relative">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-surface-400" />
              <input
                ref={inputRef}
                type="text"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder="Search stocks..."
                className="w-full pl-8 pr-3 py-2 text-sm rounded-lg
                           bg-surface-50 dark:bg-surface-900
                           border border-surface-200 dark:border-surface-700
                           focus:outline-none focus:ring-1 focus:ring-brand-500/40
                           text-surface-800 dark:text-surface-200
                           placeholder:text-surface-400"
                id="symbol-search-input"
              />
            </div>
          </div>

          {/* Options list */}
          <div className="max-h-60 overflow-y-auto">
            {filtered.length === 0 ? (
              <div className="px-4 py-3 text-sm text-surface-400 text-center">
                No stocks found
              </div>
            ) : (
              filtered.slice(0, 50).map((stock) => (
                <button
                  key={stock.symbol}
                  onClick={() => handleSelect(stock.symbol)}
                  className={`w-full px-4 py-2.5 text-left text-sm
                             hover:bg-brand-50 dark:hover:bg-brand-900/20
                             transition-colors flex items-center justify-between
                             ${selectedSymbol === stock.symbol
                               ? 'bg-brand-50 dark:bg-brand-900/20 text-brand-700 dark:text-brand-300'
                               : 'text-surface-700 dark:text-surface-300'
                             }`}
                >
                  <span className="font-semibold">{stock.symbol}</span>
                  <span className="text-xs text-surface-400 dark:text-surface-500 truncate ml-2 max-w-[150px]">
                    {stock.sector_name || stock.name || ''}
                  </span>
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
