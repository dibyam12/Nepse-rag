"""
Data Access Layer for NEPSE AI.

- OHLCV data: fetched from Neon DB via neon_client
- Indicators: computed on-demand via services.indicators
- Metadata (sectors, stocks): Django ORM on local SQLite
- All results cached to avoid redundant Neon queries
"""
import logging
import time

from apps.nepse_data.models import Stock

from services.neon_client import execute_neon_query
from services.indicators import prepare_ohlcv_dataframe, compute_all_indicators
from services.cache_service import (
    get_cached_ohlcv, cache_ohlcv,
    get_cached_indicators, cache_indicators,
    get_cached_history, cache_history,
    get_cached_symbols, cache_symbols,
    get_cached_symbol_exists, cache_symbol_exists,
)

logger = logging.getLogger('nepse_rag')


# ── OHLCV (from Neon DB) ──────────────────────────────────────

async def get_latest_ohlcv(symbol: str) -> dict:
    """
    Returns the most recent OHLCV row for symbol from Neon DB.

    Steps:
    1. Check Django cache key 'ohlcv_latest:{symbol}' (TTL 15 min)
    2. If cache miss: query Neon DB
    3. Cache result, return dict.

    Returns: {symbol, date, open, high, low, close, volume}
    Raises: ValueError if symbol has no data in Neon DB.
    """
    sym = symbol.upper()

    # 1. Check cache
    cached = get_cached_ohlcv(sym)
    if cached is not None:
        return cached

    # 2. Query Neon DB
    start = time.time()
    rows = execute_neon_query(
        "SELECT symbol, date, open, high, low, close, volume "
        "FROM stocks_stockdata "
        "WHERE symbol = %s ORDER BY date DESC LIMIT 1",
        (sym,)
    )
    latency = int((time.time() - start) * 1000)

    if not rows:
        raise ValueError(f"No OHLCV data found in Neon DB for symbol: {sym}")

    row = rows[0]
    result = {
        'symbol': row['symbol'],
        'date': str(row['date']),
        'open': float(row['open']) if row['open'] is not None else None,
        'high': float(row['high']) if row['high'] is not None else None,
        'low': float(row['low']) if row['low'] is not None else None,
        'close': float(row['close']) if row['close'] is not None else None,
        'volume': int(row['volume']) if row['volume'] is not None else 0,
    }

    # 3. Cache and return
    cache_ohlcv(sym, result)
    logger.info(
        f"Fetched latest OHLCV for {sym} from Neon ({latency}ms)",
        extra={'event': 'ohlcv_fetch', 'symbol': sym, 'latency_ms': latency}
    )
    return result


# ── Indicators (computed on-demand from Neon data) ────────────

async def get_latest_indicators(symbol: str) -> dict:
    """
    Returns freshly computed indicators for symbol.

    Steps:
    1. Check Django cache key 'indicators:{symbol}' (TTL 15 min)
    2. If cache miss:
       a. Fetch 100 rows from Neon (enough for EMA-50, MACD, BB)
       b. prepare_ohlcv_dataframe(rows) — sorts ascending
       c. compute_all_indicators(df)
    3. Cache result, return indicators dict.

    Returns: {rsi, macd, macd_signal, macd_hist, ema_20, ema_50,
              bb_upper, bb_middle, bb_lower, atr, obv, vwap, beta,
              close, volume, date, pct_change}
    Returns empty dict if symbol has fewer than 20 rows in Neon.
    """
    sym = symbol.upper()

    # 1. Check cache
    cached = get_cached_indicators(sym)
    if cached is not None:
        return cached

    # 2. Fetch from Neon
    start = time.time()
    rows = execute_neon_query(
        "SELECT symbol, date, open, high, low, close, volume "
        "FROM stocks_stockdata "
        "WHERE symbol = %s ORDER BY date DESC LIMIT 100",
        (sym,)
    )

    if len(rows) < 20:
        logger.info(f"Insufficient data for indicators: {sym} ({len(rows)} rows)")
        return {}

    # 3. Prepare DataFrame (sorts ascending internally)
    df = prepare_ohlcv_dataframe(rows)

    if df.empty:
        return {}

    # 4. Fetch market data for beta computation
    market_df = None
    try:
        market_rows = execute_neon_query(
            "SELECT date, close FROM stocks_stockdata "
            "WHERE symbol = 'NEPSE' ORDER BY date DESC LIMIT 100"
        )
        if market_rows:
            import pandas as pd
            market_df = pd.DataFrame(market_rows)
            market_df = market_df.sort_values('date').reset_index(drop=True)
            market_df['close'] = pd.to_numeric(market_df['close'], errors='coerce')
    except Exception:
        pass  # Beta will be None if market data unavailable

    # 5. Compute all indicators
    result = compute_all_indicators(df, market_df)

    latency = int((time.time() - start) * 1000)

    # 6. Cache and return
    cache_indicators(sym, result)
    logger.info(
        f"Computed indicators for {sym} ({latency}ms)",
        extra={'event': 'indicators_compute', 'symbol': sym, 'latency_ms': latency}
    )
    return result


# ── Recent History (from Neon DB) ─────────────────────────────

async def get_recent_history(symbol: str, days: int = 30) -> list[dict]:
    """
    Returns last N days of OHLCV data from Neon DB.
    Does NOT include indicators (too expensive to compute per row).

    Returns list of {symbol, date, open, high, low, close, volume}
    """
    sym = symbol.upper()

    # Check cache
    cached = get_cached_history(sym, days)
    if cached is not None:
        return cached

    # Fetch from Neon
    start = time.time()
    rows = execute_neon_query(
        "SELECT symbol, date, open, high, low, close, volume "
        "FROM stocks_stockdata "
        "WHERE symbol = %s ORDER BY date DESC LIMIT %s",
        (sym, days)
    )
    latency = int((time.time() - start) * 1000)

    result = []
    for row in rows:
        result.append({
            'symbol': row['symbol'],
            'date': str(row['date']),
            'open': float(row['open']) if row['open'] is not None else None,
            'high': float(row['high']) if row['high'] is not None else None,
            'low': float(row['low']) if row['low'] is not None else None,
            'close': float(row['close']) if row['close'] is not None else None,
            'volume': int(row['volume']) if row['volume'] is not None else 0,
        })

    # Cache and return
    cache_history(sym, days, result)
    logger.info(
        f"Fetched {len(result)} history rows for {sym} ({latency}ms)",
        extra={'event': 'history_fetch', 'symbol': sym,
               'days': days, 'latency_ms': latency}
    )
    return result


# ── Local SQLite Queries (Django ORM) ─────────────────────────

def get_sector_peers(symbol: str) -> list[str]:
    """
    Returns symbols of other stocks in the same sector.
    Queries local SQLite Stock model (not Neon).
    Returns empty list if symbol not found or has no sector.
    """
    try:
        stock = Stock.objects.get(symbol=symbol.upper())
    except Stock.DoesNotExist:
        return []

    if stock.sector is None:
        return []

    peers = Stock.objects.filter(
        sector=stock.sector,
        is_active=True,
    ).exclude(
        symbol=symbol.upper()
    ).values_list('symbol', flat=True).order_by('symbol')

    return list(peers)


def get_all_symbols() -> list[dict]:
    """
    Returns all active stocks from local SQLite.
    Each dict: {symbol, name, sector_name}
    Sorted alphabetically. Cached 24 hours.
    """
    cached = get_cached_symbols()
    if cached is not None:
        return cached

    stocks = Stock.objects.filter(
        is_active=True
    ).select_related('sector').order_by('symbol')

    result = [
        {
            'symbol': s.symbol,
            'name': s.name,
            'sector_name': s.sector.name if s.sector else None,
        }
        for s in stocks
    ]

    cache_symbols(result)
    return result


def get_stock_info(symbol: str) -> dict:
    """
    Returns full metadata for a stock from local SQLite.
    Dict: {symbol, name, sector, index, market_cap,
           listing_date, is_active}
    Raises: Stock.DoesNotExist if symbol not found.
    """
    stock = Stock.objects.select_related(
        'sector', 'index'
    ).get(symbol=symbol.upper())

    return {
        'symbol': stock.symbol,
        'name': stock.name,
        'sector': stock.sector.name if stock.sector else None,
        'index': stock.index.name if stock.index else None,
        'market_cap': stock.market_cap,
        'listing_date': str(stock.listing_date) if stock.listing_date else None,
        'is_active': stock.is_active,
    }


# ── Symbol Verification (Neon DB) ─────────────────────────────

async def verify_symbol_in_neon(symbol: str) -> bool:
    """
    Checks if symbol has any data in Neon DB.
    Used by API validation before running agent.
    Cached 1 hour.
    """
    sym = symbol.upper()

    cached = get_cached_symbol_exists(sym)
    if cached is not None:
        return cached

    rows = execute_neon_query(
        "SELECT 1 FROM stocks_stockdata WHERE symbol = %s LIMIT 1",
        (sym,)
    )
    exists = len(rows) > 0
    cache_symbol_exists(sym, exists)
    return exists
