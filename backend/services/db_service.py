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
    import asyncio
    rows = await asyncio.to_thread(
        execute_neon_query,
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
              bb_upper, bb_middle, bb_lower, atr, obv, vwap, beta, mfi,
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
    import asyncio
    rows = await asyncio.to_thread(
        execute_neon_query,
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
        market_rows = await asyncio.to_thread(
            execute_neon_query,
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
    import asyncio
    rows = await asyncio.to_thread(
        execute_neon_query,
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

    import asyncio
    rows = await asyncio.to_thread(
        execute_neon_query,
        "SELECT 1 FROM stocks_stockdata WHERE symbol = %s LIMIT 1",
        (sym,)
    )
    exists = len(rows) > 0
    cache_symbol_exists(sym, exists)
    return exists


def get_stocks_by_price_filter(sector=None, max_price=None, min_price=None, limit=15,
                                rank_by_signals=False):
    """
    Returns a list of stocks filtered by sector and/or price range.
    Uses the most recent available trading date.

    When rank_by_signals=True, computes RSI/MACD/EMA-20 for each stock
    and assigns a composite score with Buy/Sell/Neutral labels, following
    standard NEPSE market practices.
    """
    # 1. Fetch latest prices for all stocks from Neon DB
    query = """
        SELECT symbol, close, volume, date
        FROM stocks_stockdata
        WHERE date = (SELECT MAX(date) FROM stocks_stockdata)
    """
    try:
        rows = execute_neon_query(query)
        if not rows:
            return "No stocks found matching the given criteria.", []
    except Exception as e:
        return f"Error fetching price data from database: {str(e)}", []

    # 2. Query local SQLite for active stock metadata
    from apps.nepse_data.models import Stock
    django_stocks = Stock.objects.filter(is_active=True).select_related('sector')

    # Clean up and apply sector filters
    if sector:
        from apps.nepse_data.models import Sector
        if not Sector.objects.filter(name__iexact=sector).exists():
            return f"No stocks found for sector: {sector}", []
        django_stocks = django_stocks.filter(sector__name__iexact=sector)
        if not django_stocks.exists():
            return f"No stocks found for sector: {sector}", []

    stock_map = {s.symbol.upper(): s for s in django_stocks}

    # 3. Filter Neon DB rows by local SQLite mapping and price ranges
    filtered_results = []
    for row in rows:
        symbol = row['symbol'].upper()
        if symbol not in stock_map:
            continue

        stock = stock_map[symbol]
        close = float(row['close']) if row['close'] is not None else 0.0
        volume = int(row['volume']) if row['volume'] is not None else 0

        if max_price is not None and close >= max_price:
            continue
        if min_price is not None and close <= min_price:
            continue

        filtered_results.append({
            'symbol': symbol,
            'company_name': stock.name,
            'sector': stock.sector.name if stock.sector else "Unknown",
            'close': close,
            'volume': volume,
            'date': str(row['date'])
        })

    if not filtered_results:
        return "No stocks found matching the given criteria.", []

    # 4. If ranking by signals, compute indicators for each stock
    if rank_by_signals:
        filtered_results = _enrich_with_signals(filtered_results, limit)
    else:
        # Default: sort by volume descending
        filtered_results.sort(key=lambda x: x['volume'], reverse=True)
        filtered_results = filtered_results[:limit]

    if not filtered_results:
        return "No stocks found matching the given criteria.", []

    # 5. Format output lines
    result_lines = []
    for i, r in enumerate(filtered_results, 1):
        line = (
            f"{i}. {r['symbol']} — {r['company_name']} | "
            f"Sector: {r['sector']} | "
            f"Close: NPR {r['close']:.2f} | "
            f"Volume: {r['volume']:,}"
        )
        if 'signal_label' in r:
            line += f" | Signal: {r['signal_label']}"
        if 'rsi' in r and r['rsi'] is not None:
            line += f" | RSI: {r['rsi']:.1f}"
        if 'macd' in r and r['macd'] is not None:
            line += f" | MACD: {r['macd']:+.2f}"
        if 'mfi' in r and r['mfi'] is not None:
            line += f" | MFI: {r['mfi']:.1f}"
        line += f" | Date: {r['date']}"
        result_lines.append(line)

    header = f"Found {len(filtered_results)} stocks"
    if max_price is not None and min_price is not None:
        header += f" (price above NPR {min_price} and below NPR {max_price})"
    elif max_price is not None:
        header += f" (price below NPR {max_price})"
    elif min_price is not None:
        header += f" (price above NPR {min_price})"
    if rank_by_signals:
        header += ", ranked by technical signal strength"
    header += ":"

    return header + "\n" + "\n".join(result_lines), filtered_results


def _enrich_with_signals(stocks: list[dict], limit: int = 15) -> list[dict]:
    """
    Fetches RSI, MACD, EMA-20 for each filtered stock from Neon DB
    and computes a composite signal score for ranking.

    Scoring (NEPSE standard practices):
      RSI Score (40% weight):
        - RSI < 30 (oversold): 1.0  — strong buy zone
        - RSI 30-40:           0.8  — buy zone
        - RSI 40-60:           0.5  — neutral
        - RSI 60-70:           0.3  — caution zone
        - RSI > 70 (overbought): 0.1 — potential sell zone

      MACD Score (30% weight):
        - MACD > 0 and rising:  1.0  — bullish momentum
        - MACD > 0:             0.7  — positive trend
        - MACD < 0 but rising:  0.4  — recovering
        - MACD < 0:             0.1  — bearish

      EMA Score (30% weight):
        - Price > EMA-20 by > 3%: 0.8 — strong uptrend
        - Price > EMA-20:         0.6 — uptrend
        - Price ≈ EMA-20 (±1%):   0.5 — neutral
        - Price < EMA-20:         0.3 — downtrend
        - Price < EMA-20 by > 5%: 0.2 — deep discount (potential reversal)

    Labels:
      - Score >= 0.65: 🟢 Buy
      - Score 0.40-0.64: 🟡 Neutral/Hold
      - Score < 0.40: 🔴 Sell/Avoid
    """
    # Batch-fetch indicators for all symbols
    symbols = [s['symbol'] for s in stocks]

    # Limit the symbols we compute indicators for (top by volume first)
    stocks.sort(key=lambda x: x['volume'], reverse=True)
    candidates = stocks[:min(len(stocks), limit * 2)]  # fetch more than limit for better ranking

    for stock_entry in candidates:
        sym = stock_entry['symbol']
        try:
            ind_rows = execute_neon_query(
                "SELECT symbol, date, open, high, low, close, volume "
                "FROM stocks_stockdata "
                "WHERE symbol = %s ORDER BY date DESC LIMIT 50",
                (sym,)
            )
            if len(ind_rows) < 20:
                stock_entry['signal_score'] = 0.5
                stock_entry['signal_label'] = '🟡 Neutral (insufficient data)'
                continue

            df = prepare_ohlcv_dataframe(ind_rows)
            if df.empty:
                stock_entry['signal_score'] = 0.5
                stock_entry['signal_label'] = '🟡 Neutral (insufficient data)'
                continue

            indicators = compute_all_indicators(df)

            rsi = indicators.get('rsi')
            macd = indicators.get('macd')
            ema_20 = indicators.get('ema_20')
            mfi = indicators.get('mfi')
            close = stock_entry['close']

            stock_entry['rsi'] = rsi
            stock_entry['macd'] = macd
            stock_entry['ema_20'] = ema_20
            stock_entry['mfi'] = mfi

            # RSI Score (40%)
            if rsi is None:
                rsi_score = 0.5
            elif rsi < 30:
                rsi_score = 1.0
            elif rsi < 40:
                rsi_score = 0.8
            elif rsi < 60:
                rsi_score = 0.5
            elif rsi < 70:
                rsi_score = 0.3
            else:
                rsi_score = 0.1

            # MACD Score (30%)
            if macd is None:
                macd_score = 0.5
            elif macd > 0:
                macd_score = 0.7
            else:
                macd_score = 0.2

            # EMA Score (30%)
            if ema_20 is None or ema_20 == 0:
                ema_score = 0.5
            else:
                pct_from_ema = ((close - ema_20) / ema_20) * 100
                if pct_from_ema > 3:
                    ema_score = 0.8
                elif pct_from_ema > 0:
                    ema_score = 0.6
                elif pct_from_ema > -1:
                    ema_score = 0.5
                elif pct_from_ema > -5:
                    ema_score = 0.3
                else:
                    ema_score = 0.2

            composite = (rsi_score * 0.4) + (macd_score * 0.3) + (ema_score * 0.3)
            stock_entry['signal_score'] = round(composite, 3)

            if composite >= 0.65:
                stock_entry['signal_label'] = '🟢 Buy'
            elif composite >= 0.40:
                stock_entry['signal_label'] = '🟡 Neutral'
            else:
                stock_entry['signal_label'] = '🔴 Sell/Avoid'

        except Exception as e:
            logger.warning("_enrich_with_signals(%s) failed: %s", sym, e)
            stock_entry['signal_score'] = 0.5
            stock_entry['signal_label'] = '🟡 Neutral (error)'

    # Sort by signal_score descending (best buy opportunities first)
    candidates.sort(key=lambda x: x.get('signal_score', 0.5), reverse=True)
    return candidates[:limit]


# ── Historical Price Queries (from Neon DB) ───────────────────

async def get_price_at_date(symbol: str, target_date: str) -> dict | None:
    """
    Gets the closest available OHLCV row to a specific date.

    Uses a ±7 day window to find the nearest trading day.
    Returns: {symbol, date, close, open, high, low, volume} or None.
    """
    sym = symbol.upper()

    import asyncio
    from datetime import datetime, timedelta

    if isinstance(target_date, str):
        try:
            parsed = datetime.strptime(target_date, "%Y-%m-%d").date()
        except ValueError:
            logger.warning("get_price_at_date: invalid date format: %s", target_date)
            return None
    else:
        parsed = target_date

    # Search ±7 days around target to find nearest trading day
    date_from = (parsed - timedelta(days=7)).strftime("%Y-%m-%d")
    date_to = (parsed + timedelta(days=7)).strftime("%Y-%m-%d")

    start = time.time()
    rows = await asyncio.to_thread(
        execute_neon_query,
        "SELECT symbol, date, open, high, low, close, volume "
        "FROM stocks_stockdata "
        "WHERE symbol = %s AND date BETWEEN %s AND %s "
        "ORDER BY ABS(date - %s::date) ASC LIMIT 1",
        (sym, date_from, date_to, parsed.strftime("%Y-%m-%d"))
    )
    latency = int((time.time() - start) * 1000)

    if not rows:
        logger.info(
            "get_price_at_date(%s, %s): no data found",
            sym, target_date,
            extra={"event": "historical_miss", "symbol": sym},
        )
        return None

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

    logger.info(
        "get_price_at_date(%s, %s): close=%.1f on %s (%dms)",
        sym, target_date, result['close'], result['date'], latency,
        extra={"event": "historical_fetch", "symbol": sym, "latency_ms": latency},
    )
    return result


async def get_price_n_years_ago(symbol: str, years: int) -> dict | None:
    """
    Gets price closest to N years ago from today.
    Convenience wrapper around get_price_at_date.
    """
    from datetime import date, timedelta

    # Approximate N years ago (accounts for leap years)
    target = date.today() - timedelta(days=years * 365)
    return await get_price_at_date(symbol, target.strftime("%Y-%m-%d"))


async def get_price_change_summary(
    symbol: str, from_date: str, to_date: str
) -> dict:
    """
    Returns price change summary between two dates.

    If to_date is today or in the future and has no data (data lag / holiday),
    falls back to the latest available OHLCV row from get_latest_ohlcv().

    Returns: {
        symbol, from_price, from_date, to_price, to_date,
        abs_change, pct_change, direction
    }
    Returns dict with error key if from_date data is missing.
    """
    from datetime import date as date_cls

    from_data = await get_price_at_date(symbol, from_date)
    to_data = await get_price_at_date(symbol, to_date)

    # If to_date lookup failed but to_date is today or future, fall back to latest row
    if not to_data:
        try:
            parsed_to = date_cls.fromisoformat(to_date[:10])
        except (ValueError, TypeError):
            parsed_to = date_cls.today()

        if parsed_to >= date_cls.today():
            try:
                latest = await get_latest_ohlcv(symbol)
                if latest:
                    to_data = latest
                    logger.info(
                        "get_price_change_summary(%s): to_date fallback to latest row %s",
                        symbol, latest.get('date'),
                    )
            except Exception as e:
                logger.warning(
                    "get_price_change_summary(%s): latest fallback failed: %s",
                    symbol, e,
                )

    if not from_data or not to_data:
        missing = []
        if not from_data:
            missing.append(f"from_date={from_date}")
        if not to_data:
            missing.append(f"to_date={to_date}")
        return {
            "symbol": symbol.upper(),
            "error": f"No price data available for: {', '.join(missing)}",
        }

    from_price = from_data['close']
    to_price = to_data['close']
    abs_change = to_price - from_price
    pct_change = ((to_price - from_price) / from_price * 100) if from_price else 0
    direction = "increase" if abs_change > 0 else "decrease" if abs_change < 0 else "no change"

    return {
        "symbol": symbol.upper(),
        "from_price": round(from_price, 2),
        "from_date": from_data['date'],
        "to_price": round(to_price, 2),
        "to_date": to_data['date'],
        "abs_change": round(abs_change, 2),
        "pct_change": round(pct_change, 2),
        "direction": direction,
    }

