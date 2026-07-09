"""
services/non_nepse_detector.py
------------------------------
Detects when a user is asking about a stock that is NOT listed on NEPSE,
and identifies which exchange it belongs to.

Strategy (in order, fastest to slowest):
  1. Company name map — catches "Amazon", "Facebook", "Google", "Tesla" etc.
  2. Static ticker table — catches TSLA, AAPL, AMZN, META, RELIANCE etc.
  3. DuckDuckGo search — fallback for unknown symbols (3s timeout)

Public API:
    identify_non_nepse_stock(query: str, candidate_symbols: list[str]) -> dict | None
    build_non_nepse_response(symbol: str, info: dict) -> str
"""

import asyncio
import logging
from typing import Optional

logger = logging.getLogger("nepse_rag")

# ── Static ticker → (company_name, exchange) ─────────────────────────────────
# Covers the most commonly queried non-NEPSE stocks so we don't need DDG at all.
_KNOWN_NON_NEPSE_TICKERS: dict[str, tuple[str, str]] = {
    # ── US Tech / NASDAQ ──────────────────────────────────────────────────────
    "AAPL":   ("Apple Inc.",                   "NASDAQ"),
    "MSFT":   ("Microsoft Corp.",              "NASDAQ"),
    "GOOG":   ("Alphabet Inc.",                "NASDAQ"),
    "GOOGL":  ("Alphabet Inc.",                "NASDAQ"),
    "AMZN":   ("Amazon.com Inc.",              "NASDAQ"),
    "META":   ("Meta Platforms Inc.",          "NASDAQ"),
    "NVDA":   ("NVIDIA Corp.",                 "NASDAQ"),
    "TSLA":   ("Tesla Inc.",                   "NASDAQ"),
    "NFLX":   ("Netflix Inc.",                 "NASDAQ"),
    "AMD":    ("Advanced Micro Devices",       "NASDAQ"),
    "INTC":   ("Intel Corp.",                  "NASDAQ"),
    "QCOM":   ("Qualcomm Inc.",                "NASDAQ"),
    "ADBE":   ("Adobe Inc.",                   "NASDAQ"),
    "CSCO":   ("Cisco Systems",                "NASDAQ"),
    "PYPL":   ("PayPal Holdings",              "NASDAQ"),
    "COIN":   ("Coinbase Global",              "NASDAQ"),
    "SPOT":   ("Spotify Technology",           "NYSE"),
    "UBER":   ("Uber Technologies",            "NYSE"),
    "LYFT":   ("Lyft Inc.",                    "NASDAQ"),
    "ABNB":   ("Airbnb Inc.",                  "NASDAQ"),
    "SHOP":   ("Shopify Inc.",                 "NYSE"),
    "SQ":     ("Block Inc. (Square)",          "NYSE"),
    "SNAP":   ("Snap Inc.",                    "NYSE"),
    "PINS":   ("Pinterest Inc.",               "NYSE"),
    "TWTR":   ("Twitter/X Corp.",              "NYSE"),
    "DIS":    ("The Walt Disney Co.",          "NYSE"),
    "KO":     ("Coca-Cola Co.",                "NYSE"),
    "PEP":    ("PepsiCo Inc.",                 "NASDAQ"),
    "WMT":    ("Walmart Inc.",                 "NYSE"),
    "BABA":   ("Alibaba Group",                "NYSE"),
    "JD":     ("JD.com Inc.",                  "NASDAQ"),
    "BIDU":   ("Baidu Inc.",                   "NASDAQ"),
    "NIO":    ("NIO Inc.",                     "NYSE"),
    "XPEV":   ("XPeng Inc.",                   "NYSE"),
    "PLTR":   ("Palantir Technologies",        "NYSE"),
    "HOOD":   ("Robinhood Markets",            "NASDAQ"),
    # ── US Finance / NYSE ─────────────────────────────────────────────────────
    "JPM":    ("JPMorgan Chase",               "NYSE"),
    "BAC":    ("Bank of America",              "NYSE"),
    "GS":     ("Goldman Sachs",                "NYSE"),
    "MS":     ("Morgan Stanley",               "NYSE"),
    "C":      ("Citigroup Inc.",               "NYSE"),
    "WFC":    ("Wells Fargo",                  "NYSE"),
    "BRK.A":  ("Berkshire Hathaway",           "NYSE"),
    "BRK.B":  ("Berkshire Hathaway",           "NYSE"),
    "V":      ("Visa Inc.",                    "NYSE"),
    "MA":     ("Mastercard Inc.",              "NYSE"),
    "AMEX":   ("American Express",             "NYSE"),
    # ── Indian Stocks (BSE/NSE) ───────────────────────────────────────────────
    "RELIANCE":   ("Reliance Industries",         "BSE/NSE India"),
    "TCS":        ("Tata Consultancy Services",   "BSE/NSE India"),
    "INFY":       ("Infosys Ltd.",                "BSE/NSE India"),
    "INFOSYS":    ("Infosys Ltd.",                "BSE/NSE India"),
    "HDFCBANK":   ("HDFC Bank",                   "BSE/NSE India"),
    "HDFC":       ("HDFC Ltd.",                   "BSE/NSE India"),
    "ICICIBANK":  ("ICICI Bank",                  "BSE/NSE India"),
    "WIPRO":      ("Wipro Ltd.",                  "BSE/NSE India"),
    "ONGC":       ("Oil & Natural Gas Corp.",     "BSE/NSE India"),
    "TATAMOTORS": ("Tata Motors",                 "BSE/NSE India"),
    "MARUTI":     ("Maruti Suzuki",               "BSE/NSE India"),
    "ITC":        ("ITC Ltd.",                    "BSE/NSE India"),
    "AXISBANK":   ("Axis Bank",                   "BSE/NSE India"),
    "SBIN":       ("State Bank of India",         "BSE/NSE India"),
    "ZOMATO":     ("Zomato Ltd.",                 "BSE/NSE India"),
    "PAYTM":      ("One97 Communications",        "BSE/NSE India"),
    "ADANI":      ("Adani Group",                 "BSE/NSE India"),
    "ADANIPORTS": ("Adani Ports",                 "BSE/NSE India"),
    "JSWSTEEL":   ("JSW Steel",                   "BSE/NSE India"),
    "HCLTECH":    ("HCL Technologies",            "BSE/NSE India"),
    "BAJFINANCE": ("Bajaj Finance",               "BSE/NSE India"),
    "TATASTEEL":  ("Tata Steel",                  "BSE/NSE India"),
    "LT":         ("Larsen & Toubro",             "BSE/NSE India"),
    "SUNPHARMA":  ("Sun Pharmaceutical",          "BSE/NSE India"),
    "DRREDDY":    ("Dr. Reddy's Laboratories",    "BSE/NSE India"),
    "NESTLE":     ("Nestle India",                "BSE/NSE India"),
    "ULTRACEMCO": ("UltraTech Cement",            "BSE/NSE India"),
    "SENSEX":     ("BSE Sensex (Index, not stock)", "BSE India"),
    "NIFTY":      ("NSE Nifty 50 (Index, not stock)", "NSE India"),
    # ── UK / Europe ───────────────────────────────────────────────────────────
    "HSBC":  ("HSBC Holdings",                 "LSE / NYSE"),
    "BP":    ("BP plc",                        "LSE / NYSE"),
    "RIO":   ("Rio Tinto Group",               "LSE / NYSE"),
    "ARM":   ("Arm Holdings",                  "NASDAQ"),
    # ── Crypto (commonly confused with stocks) ────────────────────────────────
    "BTC":   ("Bitcoin (cryptocurrency, not a stock)", "Crypto Exchange"),
    "ETH":   ("Ethereum (cryptocurrency)",     "Crypto Exchange"),
    "BNB":   ("Binance Coin",                  "Crypto Exchange"),
    "DOGE":  ("Dogecoin",                      "Crypto Exchange"),
    "XRP":   ("Ripple XRP",                    "Crypto Exchange"),
    "SOL":   ("Solana",                        "Crypto Exchange"),
    "ADA":   ("Cardano",                       "Crypto Exchange"),
    "AVAX":  ("Avalanche",                     "Crypto Exchange"),
    "MATIC": ("Polygon",                       "Crypto Exchange"),
    "DOT":   ("Polkadot",                      "Crypto Exchange"),
}

# ── Company name → (ticker, exchange) ────────────────────────────────────────
# Catches queries like "tell me about Apple" / "how is Amazon doing"
_COMPANY_NAME_MAP: dict[str, tuple[str, str, str]] = {
    # name_lower: (ticker, company_display_name, exchange)
    "apple":          ("AAPL",   "Apple Inc.",               "NASDAQ"),
    "microsoft":      ("MSFT",   "Microsoft Corp.",          "NASDAQ"),
    "google":         ("GOOG",   "Alphabet/Google",          "NASDAQ"),
    "alphabet":       ("GOOG",   "Alphabet Inc.",            "NASDAQ"),
    "amazon":         ("AMZN",   "Amazon.com Inc.",          "NASDAQ"),
    "meta":           ("META",   "Meta Platforms Inc.",      "NASDAQ"),
    "facebook":       ("META",   "Meta Platforms Inc.",      "NASDAQ"),
    "nvidia":         ("NVDA",   "NVIDIA Corp.",             "NASDAQ"),
    "tesla":          ("TSLA",   "Tesla Inc.",               "NASDAQ"),
    "netflix":        ("NFLX",   "Netflix Inc.",             "NASDAQ"),
    "uber":           ("UBER",   "Uber Technologies",        "NYSE"),
    "airbnb":         ("ABNB",   "Airbnb Inc.",              "NASDAQ"),
    "shopify":        ("SHOP",   "Shopify Inc.",             "NYSE"),
    "spotify":        ("SPOT",   "Spotify Technology",       "NYSE"),
    "twitter":        ("TWTR",   "Twitter/X Corp.",          "NYSE"),
    "disney":         ("DIS",    "The Walt Disney Co.",      "NYSE"),
    "walmart":        ("WMT",    "Walmart Inc.",             "NYSE"),
    "alibaba":        ("BABA",   "Alibaba Group",            "NYSE"),
    "palantir":       ("PLTR",   "Palantir Technologies",    "NYSE"),
    "robinhood":      ("HOOD",   "Robinhood Markets",        "NASDAQ"),
    "coinbase":       ("COIN",   "Coinbase Global",          "NASDAQ"),
    "paypal":         ("PYPL",   "PayPal Holdings",          "NASDAQ"),
    "jpmorgan":       ("JPM",    "JPMorgan Chase",           "NYSE"),
    "goldman sachs":  ("GS",     "Goldman Sachs",            "NYSE"),
    "visa":           ("V",      "Visa Inc.",                "NYSE"),
    "mastercard":     ("MA",     "Mastercard Inc.",          "NYSE"),
    "reliance":       ("RELIANCE","Reliance Industries",     "BSE/NSE India"),
    "infosys":        ("INFY",   "Infosys Ltd.",             "BSE/NSE India"),
    "tata":           ("TCS",    "Tata Group / TCS",         "BSE/NSE India"),
    "wipro":          ("WIPRO",  "Wipro Ltd.",               "BSE/NSE India"),
    "zomato":         ("ZOMATO", "Zomato Ltd.",              "BSE/NSE India"),
    "bitcoin":        ("BTC",    "Bitcoin",                  "Crypto Exchange"),
    "ethereum":       ("ETH",    "Ethereum",                 "Crypto Exchange"),
    "dogecoin":       ("DOGE",   "Dogecoin",                 "Crypto Exchange"),
    "solana":         ("SOL",    "Solana",                   "Crypto Exchange"),
    "binance":        ("BNB",    "Binance Coin",             "Crypto Exchange"),
}


def _check_static(query_lower: str, candidate_syms: list[str]) -> Optional[dict]:
    """Check static tables. Returns info dict or None."""
    # 1. Company name scan (catches "Amazon", "Facebook", "Google" etc.)
    for name, (ticker, display, exchange) in _COMPANY_NAME_MAP.items():
        import re
        if re.search(rf'\b{re.escape(name)}\b', query_lower):
            return {
                "matched_name": name,
                "ticker": ticker,
                "company": display,
                "exchange": exchange,
                "source": "static_name_map",
            }

    # 2. Ticker symbol scan
    for sym in candidate_syms:
        sym_upper = sym.upper()
        if sym_upper in _KNOWN_NON_NEPSE_TICKERS:
            company, exchange = _KNOWN_NON_NEPSE_TICKERS[sym_upper]
            return {
                "matched_name": sym_upper,
                "ticker": sym_upper,
                "company": company,
                "exchange": exchange,
                "source": "static_ticker_map",
            }

    return None


def _ddg_lookup(symbol: str, timeout_s: float = 3.0) -> Optional[dict]:
    """
    Synchronous DDG text search for '{symbol} stock exchange listing'.
    Parses snippet for exchange keywords. Returns info dict or None.
    Should be called inside asyncio.to_thread().
    """
    try:
        from ddgs import DDGS
    except ImportError:
        return None

    _EXCHANGE_KEYWORDS = {
        "NASDAQ": "NASDAQ",
        "NYSE":   "NYSE",
        "BSE":    "BSE India",
        "NSE":    "NSE India",
        "LSE":    "London Stock Exchange",
        "TSE":    "Tokyo Stock Exchange",
        "HKEX":   "Hong Kong Stock Exchange",
        "ASX":    "Australian Securities Exchange",
        "SGX":    "Singapore Exchange",
        "CRYPTO": "Crypto Exchange",
        "BITCOIN": "Crypto Exchange",
        "ETHEREUM": "Crypto Exchange",
    }

    query = f"{symbol} stock which exchange listed"
    try:
        import socket
        old_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(timeout_s)
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=3))
        finally:
            socket.setdefaulttimeout(old_timeout)
    except Exception as e:
        logger.warning("non_nepse_detector DDG lookup failed for %s: %s", symbol, e)
        return None

    if not results:
        return None

    combined = " ".join(
        r.get("title", "") + " " + r.get("body", "")
        for r in results[:3]
    ).upper()

    found_exchange = None
    for kw, exchange_name in _EXCHANGE_KEYWORDS.items():
        if kw in combined:
            found_exchange = exchange_name
            break

    if found_exchange:
        # Try to extract company name from first result title
        first_title = results[0].get("title", symbol)
        company = first_title.split(" - ")[0].strip() if " - " in first_title else first_title
        return {
            "matched_name": symbol,
            "ticker": symbol.upper(),
            "company": company[:80],
            "exchange": found_exchange,
            "source": "ddg_search",
        }

    return None


async def identify_non_nepse_stock(
    query: str,
    candidate_symbols: list[str],
) -> Optional[dict]:
    """
    Main entry point. Returns a dict with exchange info if the query is about
    a non-NEPSE stock, or None if it cannot be determined.

    Args:
        query: The raw user query string.
        candidate_symbols: Symbols detected in the query that are NOT in the
                           NEPSE known-symbols set (i.e., rejected by extract_symbols).

    Returns:
        dict with keys: ticker, company, exchange, source
        or None if not a known non-NEPSE stock.
    """
    q_lower = query.lower()

    # Fast path: static tables (no I/O)
    info = _check_static(q_lower, candidate_symbols)
    if info:
        logger.info(
            "non_nepse_detector: matched '%s' -> %s (%s) via %s",
            info["ticker"], info["company"], info["exchange"], info["source"]
        )
        return info

    # Slow path: DDG for unknown symbols (only if we have candidates)
    if not candidate_symbols:
        return None

    sym = candidate_symbols[0]  # Check the most prominent unknown symbol
    try:
        info = await asyncio.to_thread(_ddg_lookup, sym, 3.0)
    except Exception as e:
        logger.warning("non_nepse_detector: DDG thread failed: %s", e)
        info = None

    if info:
        logger.info(
            "non_nepse_detector: DDG match '%s' -> %s (%s)",
            info["ticker"], info["company"], info["exchange"]
        )

    return info


def build_non_nepse_response(query: str, info: Optional[dict], unknown_sym: str = "") -> str:
    """
    Build a polite, informative NEPSE-only redirect response.
    Used when the user asks about a non-NEPSE stock.
    """
    sym = info["ticker"] if info else unknown_sym.upper() or "this stock"
    company = info["company"] if info else sym
    exchange = info["exchange"] if info else "a foreign exchange"

    is_crypto = info and "Crypto" in info.get("exchange", "")

    if is_crypto:
        msg = (
            f"I'm NEPSE AI — I only cover stocks listed on Nepal's stock exchange (NEPSE). "
            f"{company} ({sym}) is a cryptocurrency, not a NEPSE-listed stock, so it's outside "
            f"my coverage. For crypto prices and analysis, check coinmarketcap.com or binance.com. "
            f"If you'd like to discuss NEPSE-listed stocks — banks, hydropower, insurance, "
            f"microfinance — I'm here to help."
        )
    else:
        nepse_examples = "NABIL (banking), NLIC (insurance), ADBL (development bank)"
        msg = (
            f"I'm NEPSE AI — I only cover stocks listed on Nepal's stock exchange (NEPSE). "
            f"{company} ({sym}) is listed on {exchange}, not NEPSE, so it's outside my coverage. "
            f"For {sym} data, check finance.yahoo.com or your broker's platform. "
            f"If you'd like to discuss NEPSE-listed stocks — for example, {nepse_examples} — "
            f"I'm here to help."
        )

    return msg + "\n\nDISCLAIMER: This is for educational purposes only. Not financial advice."


def extract_unknown_symbols_from_query(query: str) -> list[str]:
    """
    Extracts ALL-CAPS word-like tokens from query that look like tickers
    but are NOT in the NEPSE symbol set. Used to find candidate non-NEPSE symbols.
    """
    import re
    candidates = re.findall(r'\b([A-Za-z]{2,10})\b', query)
    known_nepse = _get_nepse_symbols()

    # Also check company name map for full word matches
    q_lower = query.lower()
    for name in _COMPANY_NAME_MAP:
        if re.search(rf'\b{re.escape(name)}\b', q_lower):
            return [_COMPANY_NAME_MAP[name][0]]  # return the ticker

    unknown = []
    seen = set()
    _NOISE = {
        "I", "A", "THE", "IS", "IN", "AT", "TO", "BY", "OR", "AND",
        "FOR", "ON", "BE", "DO", "IT", "NO", "SO", "UP", "US", "IF",
        "MY", "WE", "AS", "AN", "AM", "ME", "OK", "NOT", "CAN",
        "RSI", "MACD", "EMA", "SMA", "ATR", "OBV", "MFI", "BB",
        "NEPSE", "NRB", "SEBON", "IPO", "LTP", "NPR", "AGM",
        "BUY", "SELL", "HOLD", "BULL", "BEAR", "NEWS",
    }
    for c in candidates:
        c_upper = c.upper()
        if c_upper in seen or c_upper in _NOISE:
            continue
        if known_nepse and c_upper in known_nepse:
            continue  # it IS a NEPSE stock
        if len(c_upper) < 2 or len(c_upper) > 8:
            continue
        seen.add(c_upper)
        unknown.append(c_upper)

    return unknown


_NEPSE_SYMBOLS_CACHE: Optional[set] = None


def _get_nepse_symbols() -> set:
    """Lazy-load NEPSE symbols from DB (cached)."""
    global _NEPSE_SYMBOLS_CACHE
    if _NEPSE_SYMBOLS_CACHE is None:
        try:
            from services.query_router import get_known_symbols
            _NEPSE_SYMBOLS_CACHE = get_known_symbols()
        except Exception:
            _NEPSE_SYMBOLS_CACHE = set()
    return _NEPSE_SYMBOLS_CACHE
