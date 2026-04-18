"""
On-demand technical indicator computation.

Input: pandas DataFrame with OHLCV columns from Neon DB.
Output: computed indicator values (latest single values or full dict).
No database interaction — pure pandas/pandas_ta computation.

Includes: RSI, MACD, EMA, Bollinger Bands, ATR, OBV, VWAP, Beta.
"""

import pandas as pd
import pandas_ta as ta
import logging

logger = logging.getLogger('nepse_rag')


def prepare_ohlcv_dataframe(rows: list[dict]) -> pd.DataFrame:
    """
    Converts list of dicts from Neon DB query into a clean DataFrame.
    - Sorts by date ascending (required for indicator computation)
    - Ensures columns: open, high, low, close, volume are float/int
    - Drops rows with null close prices

    Input: [{'symbol': 'NABIL', 'date': date, 'open': ..., 'close': ...}]
    Returns: cleaned pandas DataFrame sorted by date ascending.
    """
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    # Sort by date ascending (oldest first) for indicator computation
    df = df.sort_values('date').reset_index(drop=True)

    # Ensure numeric types
    for col in ['open', 'high', 'low', 'close']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    if 'volume' in df.columns:
        df['volume'] = pd.to_numeric(df['volume'], errors='coerce').fillna(0).astype(int)

    # Drop rows with null close prices
    df = df.dropna(subset=['close']).reset_index(drop=True)

    return df


def compute_rsi(df: pd.DataFrame, period: int = 14) -> float | None:
    """
    Computes RSI for the most recent row.
    Returns the latest RSI value as float, or None if insufficient data.
    Requires at least period+1 rows (15 rows for default period=14).
    """
    if len(df) < period + 1:
        return None
    try:
        rsi = ta.rsi(df['close'], length=period)
        val = rsi.iloc[-1]
        return round(float(val), 4) if pd.notna(val) else None
    except Exception as e:
        logger.warning(f"RSI computation failed: {e}")
        return None


def compute_macd(df: pd.DataFrame,
                 fast: int = 12,
                 slow: int = 26,
                 signal: int = 9) -> dict | None:
    """
    Computes MACD for the most recent row.
    Returns dict: {macd, macd_signal, macd_hist} or None.
    Requires at least slow+signal rows (35 rows for defaults).
    """
    if len(df) < slow + signal:
        return None
    try:
        macd_result = ta.macd(df['close'], fast=fast, slow=slow, signal=signal)
        if macd_result is None:
            return None
        last = macd_result.iloc[-1]
        return {
            'macd': round(float(last.iloc[0]), 6) if pd.notna(last.iloc[0]) else None,
            'macd_signal': round(float(last.iloc[1]), 6) if pd.notna(last.iloc[1]) else None,
            'macd_hist': round(float(last.iloc[2]), 6) if pd.notna(last.iloc[2]) else None,
        }
    except Exception as e:
        logger.warning(f"MACD computation failed: {e}")
        return None


def compute_ema(df: pd.DataFrame, period: int) -> float | None:
    """
    Computes EMA for given period, returns latest value.
    Returns None if fewer rows than period.
    """
    if len(df) < period:
        return None
    try:
        ema = ta.ema(df['close'], length=period)
        val = ema.iloc[-1]
        return round(float(val), 2) if pd.notna(val) else None
    except Exception as e:
        logger.warning(f"EMA-{period} computation failed: {e}")
        return None


def compute_bollinger_bands(df: pd.DataFrame,
                            period: int = 20,
                            std: float = 2.0) -> dict | None:
    """
    Computes Bollinger Bands for the most recent row.
    Returns dict: {bb_upper, bb_middle, bb_lower} or None.
    Requires at least period rows (20 rows for default).
    """
    if len(df) < period:
        return None
    try:
        bb_result = ta.bbands(df['close'], length=period, std=std)
        if bb_result is None:
            return None
        last = bb_result.iloc[-1]
        return {
            'bb_lower': round(float(last.iloc[0]), 2) if pd.notna(last.iloc[0]) else None,
            'bb_middle': round(float(last.iloc[1]), 2) if pd.notna(last.iloc[1]) else None,
            'bb_upper': round(float(last.iloc[2]), 2) if pd.notna(last.iloc[2]) else None,
        }
    except Exception as e:
        logger.warning(f"Bollinger Bands computation failed: {e}")
        return None


def compute_atr(df: pd.DataFrame, period: int = 14) -> float | None:
    """
    Computes Average True Range for the most recent row.
    Returns latest ATR value as float, or None if insufficient data.
    Requires at least period+1 rows.
    """
    if len(df) < period + 1:
        return None
    try:
        atr = ta.atr(df['high'], df['low'], df['close'], length=period)
        val = atr.iloc[-1]
        return round(float(val), 4) if pd.notna(val) else None
    except Exception as e:
        logger.warning(f"ATR computation failed: {e}")
        return None


def compute_obv(df: pd.DataFrame) -> float | None:
    """
    Computes On-Balance Volume for the most recent row.
    Returns latest OBV value as float, or None.
    """
    if len(df) < 2:
        return None
    try:
        obv = ta.obv(df['close'], df['volume'])
        val = obv.iloc[-1]
        return round(float(val), 2) if pd.notna(val) else None
    except Exception as e:
        logger.warning(f"OBV computation failed: {e}")
        return None


def compute_vwap(df: pd.DataFrame) -> float | None:
    """
    Computes Volume Weighted Average Price for the most recent row.
    Approximated using OHLC data.
    Returns latest VWAP as float, or None.
    """
    if len(df) < 1 or 'volume' not in df.columns:
        return None
    try:
        temp_df = df.copy()
        temp_df.index = pd.to_datetime(temp_df['date'])
        vwap_res = ta.vwap(temp_df['high'], temp_df['low'],
                           temp_df['close'], temp_df['volume'])
        if vwap_res is None:
            return None
        val = vwap_res.iloc[-1]
        return round(float(val), 2) if pd.notna(val) else None
    except Exception as e:
        logger.warning(f"VWAP computation failed: {e}")
        return None


def compute_beta(df: pd.DataFrame,
                 market_df: pd.DataFrame,
                 period: int = 20) -> float | None:
    """
    Computes Beta (stock vs market) for the most recent row.
    Beta = Covariance(stock_returns, market_returns) / Variance(market_returns)
    Returns latest Beta as float, or None if insufficient data.

    Args:
        df: Stock OHLCV DataFrame (must have 'date' and 'close')
        market_df: Market index OHLCV DataFrame (must have 'date' and 'close')
        period: Rolling window for beta calculation (default 20)
    """
    if market_df is None or market_df.empty or len(df) < period:
        return None
    try:
        merged = pd.merge(
            df[['date', 'close']], market_df[['date', 'close']],
            on='date', suffixes=('_stock', '_market')
        )
        merged.sort_values('date', inplace=True)

        if len(merged) < period:
            return None

        stock_ret = merged['close_stock'].pct_change()
        market_ret = merged['close_market'].pct_change()

        cov = stock_ret.rolling(window=period).cov(market_ret)
        var = market_ret.rolling(window=period).var()
        beta = cov / var

        val = beta.iloc[-1]
        return round(float(val), 4) if pd.notna(val) else None
    except Exception as e:
        logger.warning(f"Beta computation failed: {e}")
        return None


def compute_all_indicators(df: pd.DataFrame,
                           market_df: pd.DataFrame = None) -> dict:
    """
    Computes ALL indicators in one call.
    Returns complete dict ready for tool output:
    {
      rsi, macd, macd_signal, macd_hist,
      ema_20, ema_50, bb_upper, bb_middle, bb_lower,
      atr, obv, vwap, beta,
      close, open, high, low, volume, date,
      pct_change
    }
    Any indicator that cannot be computed (insufficient data)
    is set to None — never raises exceptions.
    """
    result = {
        'rsi': None, 'macd': None, 'macd_signal': None, 'macd_hist': None,
        'ema_20': None, 'ema_50': None,
        'bb_upper': None, 'bb_middle': None, 'bb_lower': None,
        'atr': None, 'obv': None, 'vwap': None, 'beta': None,
        'close': None, 'open': None, 'high': None, 'low': None,
        'volume': None, 'date': None, 'pct_change': None,
    }

    if df.empty:
        return result

    # Latest OHLCV values
    last_row = df.iloc[-1]
    result['close'] = float(last_row['close']) if pd.notna(last_row.get('close')) else None
    result['open'] = float(last_row['open']) if pd.notna(last_row.get('open')) else None
    result['high'] = float(last_row['high']) if pd.notna(last_row.get('high')) else None
    result['low'] = float(last_row['low']) if pd.notna(last_row.get('low')) else None
    result['volume'] = int(last_row['volume']) if pd.notna(last_row.get('volume')) else None
    result['date'] = str(last_row['date']) if 'date' in last_row else None

    # Percentage change from previous close
    if len(df) >= 2:
        prev_close = float(df.iloc[-2]['close'])
        curr_close = float(df.iloc[-1]['close'])
        if prev_close != 0:
            result['pct_change'] = round(
                (curr_close - prev_close) / prev_close * 100, 4
            )

    # Compute all indicators
    result['rsi'] = compute_rsi(df)

    macd_data = compute_macd(df)
    if macd_data:
        result['macd'] = macd_data['macd']
        result['macd_signal'] = macd_data['macd_signal']
        result['macd_hist'] = macd_data['macd_hist']

    result['ema_20'] = compute_ema(df, 20)
    result['ema_50'] = compute_ema(df, 50)

    bb_data = compute_bollinger_bands(df)
    if bb_data:
        result['bb_upper'] = bb_data['bb_upper']
        result['bb_middle'] = bb_data['bb_middle']
        result['bb_lower'] = bb_data['bb_lower']

    result['atr'] = compute_atr(df)
    result['obv'] = compute_obv(df)
    result['vwap'] = compute_vwap(df)
    result['beta'] = compute_beta(df, market_df)

    return result
