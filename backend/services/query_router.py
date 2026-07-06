"""
Query Router for NEPSE AI Agent — Phase 4.

Replaces Phase 3's 6-intent system with a cleaner 4-route schema
optimized for the LangGraph agent workflow.

Routes:
    ROUTE_FULL_AGENT  — why, news, today, fell, rose, latest...
    ROUTE_COMPARE     — compare, vs, better, both... OR ≥2 symbols
    ROUTE_SQL_GRAPH   — rsi, macd, price, volume, sector, peer...
    ROUTE_VECTOR_ONLY — default (educational, definitional queries)

Public API:
    classify_query(question, symbol) -> RouteDecision
    extract_symbols(question) -> list[str]
"""

import re
import logging
from dataclasses import dataclass, field

logger = logging.getLogger('nepse_rag')

# ── Route Constants ───────────────────────────────────────────
ROUTE_VECTOR_ONLY = "vector_only"
ROUTE_SQL_GRAPH   = "sql_graph"
ROUTE_FULL_AGENT  = "full_agent"
ROUTE_COMPARE     = "compare"
ROUTE_CHAT        = "chat"

# ── Chat / Conversational Patterns ───────────────────────────
# Matched BEFORE any stock routing. Regex patterns, case-insensitive.
CHAT_PATTERNS = [
    r"\b(hi|hello|hey|howdy|greetings|yo)\b",
    r"\bhow are you\b",
    r"\bwhat'?s up\b",
    r"\bthank(s| you)\b",
    r"\bgood (morning|afternoon|evening|night)\b",
    r"\bwho are you\b",
    r"\bintroduce yourself\b",
    r"\bwhat can you do\b",
    r"\bare you (an |a )?ai\b",
    r"^(ok|okay|cool|nice|great|got it|alright)\.?$",
]

# ── Keywords Per Route ────────────────────────────────────────
FULL_AGENT_KEYWORDS = [
    "why", "reason", "cause", "impact", "news", "today",
    "recent", "movement", "fell", "rose", "dropped",
    "increased", "happened", "affect", "because",
    "analysis", "outlook", "forecast", "should i buy", "worth",
    "what happened", "crash", "surge", "rally", "dump",
    "status", "update", "market",
    "fundamental", "eps", "profit", "npl", "earnings",
    "balance sheet", "revenue", "pe ratio",
    # Temporal keywords — trigger historical data fetching
    "years ago", "year ago", "last year", "historically",
    "history", "historical", "changed", "over time",
]

COMPARE_KEYWORDS = [
    "compare", "vs", "versus", "better", "worse",
    "difference", "between", "which one", "both",
    "stronger", "weaker", "higher", "lower than",
]

SQL_GRAPH_KEYWORDS = [
    "rsi", "macd", "ema", "signal", "price", "volume",
    "indicator", "technical", "close", "open", "high", "low",
    "sector", "peer", "performance", "ohlcv", "bollinger",
    "chart", "data", "number", "value", "current", "today's",
    "show", "signals", "atr", "obv", "vwap", "beta",
]

# ── Common words to exclude from symbol extraction ───────────
_EXCLUDED_WORDS = frozenset({
    # Common English
    "I", "A", "OR", "AND", "IS", "IN", "AT", "TO", "BY", "OF",
    "ON", "BE", "DO", "IT", "NO", "SO", "UP", "US", "IF", "GO",
    "MY", "WE", "AS", "AN", "AM", "HE", "ME", "OK",
    # Longer common words
    "THE", "FOR", "ARE", "BUT", "CAN", "HAS", "HAD", "WAS",
    "ALL", "ANY", "FEW", "HOW", "ITS", "MAY", "NEW", "NOW",
    "OLD", "OUR", "OWN", "SAY", "SHE", "TOO", "USE", "HER",
    "HIM", "HIS", "LET", "PUT", "TOP", "TRY", "WHO", "WHY",
    "BIG", "END", "FAR", "GET", "GOT", "RUN", "SET", "SIT",
    "TEN", "YES", "YET", "NOT", "OUT",
    # Additional false-positive words (common in financial queries)
    "BOD", "NET", "FEE", "AIM", "KEY", "LOW", "ODD", "MAP",
    "LOG", "TAX", "PAY", "CUT", "LED", "RAN", "FIT", "GAP",
    "MET", "WON", "API", "ADD", "AVG", "MAX", "MIN", "SUM",
    "DAY", "PER", "ALSO", "BEST", "JUST", "ONLY", "VERY",
    "WHAT", "WHEN", "WILL", "WITH", "YOUR", "GOOD", "MUCH",
    "SOME", "THAN", "THEM", "THEN", "THIS", "THAT", "FROM",
    "SHOW", "TELL", "GIVE", "TAKE", "MAKE", "LIKE", "LIST",
    "FALL", "FELL", "RISE", "ROSE", "DROP", "HIGH", "OPEN",
    # Trading terms (not tickers)
    "BUY", "SELL", "HOLD", "LONG", "SHORT", "BULL", "BEAR",
    # Indicator abbreviations (not tickers)
    "RSI", "MACD", "EMA", "SMA", "ATR", "OBV", "VWAP", "BB",
    # Institution abbreviations
    "AGM", "NRB", "SEBON", "CDSC", "GDP", "NPR",
    "CEO", "CFO", "USA", "NEPSE",
})


# ── Merged / Historical Symbols Mapping ────────────────────────
MERGED_SYMBOLS_MAP = {
    "NCCB": "KBL",      # Nepal Credit and Commerce Bank -> Kumari Bank
    "MEGA": "NIMB",     # Mega Bank -> Nepal Investment Mega Bank
    "NIB": "NIMB",      # Nepal Investment Bank -> Nepal Investment Mega Bank
    "BOKL": "GBIME",    # Bank of Kathmandu -> Global IME Bank
    "CBL": "LSL",       # Sunrise Bank -> Laxmi Sunrise Bank
    "LBL": "LSL",       # Laxmi Bank -> Laxmi Sunrise Bank
}


# ── Temporal Patterns ─────────────────────────────────────────
TEMPORAL_PATTERNS = [
    (r'(\d+)\s*years?\s*ago',       'years_ago'),    # "3 years ago"
    (r'price\s*(?:in|of|from)\s*(\d{4})', 'year'),   # "price in 2023"
    (r'last\s*(\d+)\s*years?',      'years_ago'),    # "last 3 years"
    (r'(?:since|from)\s*(\d{4})',   'year'),          # "since 2020"
    (r'\b(\d{4})\b.*(?:price|close|data)', 'year'),   # "2023 price"
    (r'(?:history|historical)',      'history'),       # "price history"
    (r'how much.*(?:changed|change)', 'change'),       # "how much has it changed"
]


def extract_temporal_params(question: str) -> dict:
    """Extract temporal parameters from a question.
    Returns: {years_ago: int} or {target_year: int} or {} if not temporal."""
    from datetime import date
    q_lower = question.lower()
    for pattern, param_type in TEMPORAL_PATTERNS:
        match = re.search(pattern, q_lower)
        if match:
            if param_type == 'years_ago':
                return {'years_ago': int(match.group(1))}
            elif param_type == 'year':
                year = int(match.group(1))
                if 1990 <= year <= date.today().year:
                    return {'target_year': year}
            elif param_type == 'history':
                return {'years_ago': 5}  # Default: show 5 year history
            elif param_type == 'change':
                return {'years_ago': 3}  # Default: compare vs 3 years ago
    return {}


@dataclass
class RouteDecision:
    """
    Result of query routing.

    Attributes:
        route: One of ROUTE_VECTOR_ONLY, ROUTE_SQL_GRAPH,
               ROUTE_FULL_AGENT, ROUTE_COMPARE, ROUTE_CHAT, ROUTE_SCREENER.
        symbols: Extracted NEPSE ticker symbols from the query.
        tools_needed: List of tool names the agent will call.
        temporal_params: {years_ago: int} or {target_year: int} for historical queries.
    """
    route: str
    symbols: list = field(default_factory=list)
    tools_needed: list = field(default_factory=list)
    price_below: int = None
    price_above: int = None
    sector: str = None
    temporal_params: dict = field(default_factory=dict)


_KNOWN_SYMBOLS = None

_COMPANY_NAMES_MAP = None

def _fetch_symbols_from_db():
    from django.apps import apps
    Stock = apps.get_model('nepse_data', 'Stock')
    return set(s.upper() for s in Stock.objects.values_list('symbol', flat=True))

def get_known_symbols():
    global _KNOWN_SYMBOLS
    if _KNOWN_SYMBOLS is None:
        try:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=1) as executor:
                _KNOWN_SYMBOLS = executor.submit(_fetch_symbols_from_db).result()
        except Exception as e:
            logger.warning("Failed to load symbols for query router: %s", e)
            _KNOWN_SYMBOLS = set()
    return _KNOWN_SYMBOLS

def _fetch_company_names_from_db():
    from django.apps import apps
    Stock = apps.get_model('nepse_data', 'Stock')
    mapping = {}
    for symbol, name in Stock.objects.values_list('symbol', 'name'):
        if name and "auto-created" not in name.lower():
            clean_name = name.lower().strip()
            mapping[clean_name] = symbol
            
            # Map first two words of company name
            words = clean_name.split()
            if len(words) >= 2:
                two_words = " ".join(words[:2])
                # Exclude generic two-word combinations
                if two_words not in ("mutual fund", "investment company", "limited company"):
                    mapping[two_words] = symbol
    return mapping

def get_company_names_map():
    global _COMPANY_NAMES_MAP
    if _COMPANY_NAMES_MAP is None:
        try:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=1) as executor:
                _COMPANY_NAMES_MAP = executor.submit(_fetch_company_names_from_db).result()
        except Exception as e:
            logger.warning("Failed to load company name mapping: %s", e)
            _COMPANY_NAMES_MAP = {}
    return _COMPANY_NAMES_MAP

def extract_symbols(question: str) -> list[str]:
    """
    Extracts NEPSE stock symbols from question text.
    Uses case-insensitive matching against known symbols and company names.
    Supports historical/merged symbols mapped to active entities.
    """
    seen = set()
    symbols = []

    # 1. Try matching company names first
    q_lower = question.lower()
    name_map = get_company_names_map()
    for name, sym in name_map.items():
        pattern = rf"\b{re.escape(name)}\b"
        if re.search(pattern, q_lower):
            sym_upper = sym.upper()
            if sym_upper not in seen:
                seen.add(sym_upper)
                symbols.append(sym_upper)

    # 2. Match ticker symbol candidates
    candidates = re.findall(r'\b([A-Za-z0-9]{2,10})\b', question)
    known = get_known_symbols()
    
    for c in candidates:
        c_upper = c.upper()
        if c_upper in seen or c_upper in _EXCLUDED_WORDS:
            continue
            
        # Allow historical/merged symbols to be recognized
        if c_upper in MERGED_SYMBOLS_MAP:
            seen.add(c_upper)
            symbols.append(c_upper)
            continue
            
        if known and c_upper not in known:
            continue
            
        if not known and not c.isupper():
            # Fallback if DB not ready: only accept ALL CAPS words
            continue
            
        seen.add(c_upper)
        symbols.append(c_upper)

    return symbols


def _has_keyword(text: str, keywords: list[str]) -> bool:
    """Checks if any keyword in the list matches the text with word boundaries."""
    for kw in keywords:
        pattern = rf"\b{re.escape(kw.lower())}\b"
        if re.search(pattern, text):
            return True
    return False


def classify_query(question: str, symbol: str = None) -> RouteDecision:
    """
    Classifies query into one of 4 routes.

    Check order (most specific first):
    1. ROUTE_COMPARE     -> if any COMPARE_KEYWORDS found OR >=2 symbols
    2. ROUTE_FULL_AGENT  -> if any FULL_AGENT_KEYWORDS found
    3. Definitional      -> if definitional pattern + no symbols -> vector_only
    4. ROUTE_SQL_GRAPH   -> if any SQL_GRAPH_KEYWORDS found
    5. ROUTE_VECTOR_ONLY -> default (educational, definitional)

    Args:
        question: User's natural language question.
        symbol: Optional symbol to include ONLY if no symbols are in the question.

    Returns:
        RouteDecision with route, symbols, and tools_needed.
    """
    # --- Screener route: "recommend banks below 200", "stocks under 300", etc. ---
    SCREENER_PATTERNS = [
        r'\brecommend\b.*\b(bank|stock|share|company)\b',
        r'\b(bank|stock|share|company)\b.*\brecommend\b',
        r'\bbelow\s+\d+\b',
        r'\bunder\s+\d+\b',
        r'\babove\s+\d+\b',
        r'\bwatch.?list\b',
        r'\bscreen\b',
        r'\bfilter\b.*\b(price|npr|rupee)\b',
        r'\baffordable\b',
        r'\bcheap(er)?\b',
    ]

    if any(re.search(p, question, re.IGNORECASE) for p in SCREENER_PATTERNS):
        price_below = None
        price_above = None
        
        m = re.search(r'\bbelow\s+(\d+)\b', question, re.IGNORECASE)
        if m:
            price_below = int(m.group(1))
        
        m = re.search(r'\bunder\s+(\d+)\b', question, re.IGNORECASE)
        if m:
            price_below = int(m.group(1))
        
        m = re.search(r'\babove\s+(\d+)\b', question, re.IGNORECASE)
        if m:
            price_above = int(m.group(1))
        
        # Extract sector if mentioned
        sector = None
        sector_keywords = {
            'commercial bank': 'Commercial Banks',
            'development bank': 'Development Banks',
            'finance': 'Finance',
            'insurance': 'Life Insurance',
            'hydropower': 'Hydropower',
            'microfinance': 'Microfinance',
            'manufacturing': 'Manufacturing And Processing',
        }
        for kw, sector_name in sector_keywords.items():
            if kw in question.lower():
                sector = sector_name
                break
        
        logger.info(
            "Query routed to screener: '%s' (sector=%s, price_below=%s, price_above=%s)",
            question[:60], sector, price_below, price_above,
            extra={"event": "query_route", "route": "screener", "symbols": []},
        )
        return RouteDecision(
            route='screener',
            symbols=[],
            tools_needed=['sql_tool'],
            price_below=price_below,
            price_above=price_above,
            sector=sector
        )

    q_lower = question.lower()

    # 0. Chat — casual conversation detected FIRST, no stock data needed
    for pat in CHAT_PATTERNS:
        if re.search(pat, q_lower):
            logger.info(
                "Query routed to chat: '%s'",
                question[:60],
                extra={"event": "query_route", "route": ROUTE_CHAT, "symbols": []},
            )
            return RouteDecision(route=ROUTE_CHAT, symbols=[], tools_needed=[])

    # Extract symbols from question text
    symbols = extract_symbols(question)

    # Only inject the context symbol if no symbols were explicitly found in the text
    if not symbols and symbol:
        sym_upper = symbol.upper()
        symbols.append(sym_upper)

    # Evaluate definitional vs data patterns first for the _decide helper
    PRICE_DATA_KEYWORDS = [
        "price", "latest", "current", "today", "now", "close",
        "data", "number", "value", "show"
    ]
    definitional_patterns = [
        "what is", "what are", "what does", "define", "explain",
        "meaning of", "how does", "how do", "tell me about",
        "describe", "introduction to", "basics of",
    ]
    # "tell me about NABIL" = stock query, NOT definitional
    # Only definitional when no symbols present (e.g., "what is RSI?")
    is_definitional = any(pat in q_lower for pat in definitional_patterns) and not symbols
    wants_data = _has_keyword(q_lower, PRICE_DATA_KEYWORDS)

    # Helper to build and log decision
    def _decide(route, tools):
        # Block vector_tool for COMPARE (never needed) or when explicitly asking
        # for data/price/news without a definitional question
        if "vector_tool" in tools:
            if route == ROUTE_COMPARE:
                tools = [t for t in tools if t != "vector_tool"]
            elif not is_definitional and (wants_data or _has_keyword(q_lower, ["news", "latest"])):
                tools = [t for t in tools if t != "vector_tool"]

        decision = RouteDecision(
            route=route, symbols=symbols, tools_needed=tools,
            temporal_params=extract_temporal_params(question),
        )
        logger.info(
            "Query routed to %s: '%s' (symbols=%s, temporal=%s)",
            route, question[:60], symbols, decision.temporal_params or None,
            extra={"event": "query_route", "route": route, "symbols": symbols},
        )
        return decision

    # 1. Compare — HIGHEST priority (most specific: >=2 symbols or explicit keywords)
    if _has_keyword(q_lower, COMPARE_KEYWORDS) or len(symbols) >= 2:
        return _decide(ROUTE_COMPARE, ["sql_tool", "graph_tool", "news_tool"])

    # 2. Full agent — why/news/today with a single symbol
    if _has_keyword(q_lower, FULL_AGENT_KEYWORDS):
        return _decide(ROUTE_FULL_AGENT,
                       ["sql_tool", "graph_tool", "news_tool", "vector_tool"])

    # 3. Definitional queries — "what is X", "explain X", "define X"
    #    Only route to vector_only if it's truly educational
    #    (no stock symbol AND no request for live data)
    if is_definitional and not symbols and not wants_data:
        return _decide(ROUTE_VECTOR_ONLY, ["vector_tool"])

    # 4. SQL + Graph — technical analysis, price data
    #    BUT: if temporal intent detected, upgrade to full_agent so historical_tool fires
    if _has_keyword(q_lower, SQL_GRAPH_KEYWORDS):
        temporal = extract_temporal_params(question)
        if temporal:
            return _decide(ROUTE_FULL_AGENT,
                           ["sql_tool", "graph_tool", "news_tool", "historical_tool"])
        return _decide(ROUTE_SQL_GRAPH, ["sql_tool", "graph_tool"])

    # 5. If symbols are present but no keyword matched, default to full_agent
    #    "tell me about NABIL" → should still fetch SQL data + news
    if symbols:
        return _decide(ROUTE_FULL_AGENT,
                       ["sql_tool", "graph_tool", "news_tool"])

    # 6. Vector only — educational, definitional (default, no symbols)
    return _decide(ROUTE_VECTOR_ONLY, ["vector_tool"])

