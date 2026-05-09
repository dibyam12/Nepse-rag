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

# ── Keywords Per Route ────────────────────────────────────────
FULL_AGENT_KEYWORDS = [
    "why", "reason", "cause", "impact", "news", "today",
    "recent", "movement", "fell", "rose", "dropped",
    "increased", "happened", "affect", "because",
    "analysis", "outlook", "forecast", "should i buy", "worth",
    "what happened", "crash", "surge", "rally", "dump",
    "status", "update", "market",
    "fundamental", "eps", "profit", "npl", "earnings",
    "balance sheet", "revenue", "pe ratio"
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
    # Trading terms (not tickers)
    "BUY", "SELL", "HOLD", "LONG", "SHORT", "BULL", "BEAR",
    # Indicator abbreviations (not tickers)
    "RSI", "MACD", "EMA", "SMA", "ATR", "OBV", "VWAP", "BB",
    # Institution abbreviations
    "AGM", "NRB", "SEBON", "CDSC", "GDP", "NPR",
    "CEO", "CFO", "USA",
})


@dataclass
class RouteDecision:
    """
    Result of query routing.

    Attributes:
        route: One of ROUTE_VECTOR_ONLY, ROUTE_SQL_GRAPH,
               ROUTE_FULL_AGENT, ROUTE_COMPARE.
        symbols: Extracted NEPSE ticker symbols from the query.
        tools_needed: List of tool names the agent will call.
    """
    route: str
    symbols: list = field(default_factory=list)
    tools_needed: list = field(default_factory=list)


_KNOWN_SYMBOLS = None

def get_known_symbols():
    global _KNOWN_SYMBOLS
    if _KNOWN_SYMBOLS is None:
        try:
            from django.apps import apps
            Stock = apps.get_model('nepse_data', 'Stock')
            _KNOWN_SYMBOLS = set(s.upper() for s in Stock.objects.values_list('symbol', flat=True))
        except Exception as e:
            logger.warning("Failed to load symbols for query router: %s", e)
            _KNOWN_SYMBOLS = set()
    return _KNOWN_SYMBOLS

def extract_symbols(question: str) -> list[str]:
    """
    Extracts NEPSE stock symbols from question text.
    Uses case-insensitive matching against the database of known symbols.
    """
    candidates = re.findall(r'\b([A-Za-z0-9]{2,10})\b', question)
    known = get_known_symbols()
    
    seen = set()
    symbols = []
    for c in candidates:
        c_upper = c.upper()
        if c_upper in seen or c_upper in _EXCLUDED_WORDS:
            continue
            
        if known and c_upper not in known:
            continue
            
        if not known and not c.isupper():
            # Fallback if DB not ready: only accept ALL CAPS words
            continue
            
        seen.add(c_upper)
        symbols.append(c_upper)

    return symbols


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
        symbol: Optional symbol to include even if not in question.

    Returns:
        RouteDecision with route, symbols, and tools_needed.
    """
    q_lower = question.lower()

    # Extract symbols from question text
    symbols = extract_symbols(question)

    # If caller provided a symbol, ensure it's in the list
    if symbol:
        sym_upper = symbol.upper()
        if sym_upper not in symbols:
            symbols.insert(0, sym_upper)

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
    wants_data = any(kw in q_lower for kw in PRICE_DATA_KEYWORDS)

    # Helper to build and log decision
    def _decide(route, tools):
        # Block vector_tool for COMPARE (never needed) or when explicitly asking
        # for data/price/news without a definitional question
        if "vector_tool" in tools:
            if route == ROUTE_COMPARE:
                tools = [t for t in tools if t != "vector_tool"]
            elif not is_definitional and (wants_data or any(kw in q_lower for kw in ["news", "latest"])):
                tools = [t for t in tools if t != "vector_tool"]

        decision = RouteDecision(route=route, symbols=symbols, tools_needed=tools)
        logger.info(
            "Query routed to %s: '%s' (symbols=%s)",
            route, question[:60], symbols,
            extra={"event": "query_route", "route": route, "symbols": symbols},
        )
        return decision

    # 1. Compare — HIGHEST priority (most specific: >=2 symbols or explicit keywords)
    if any(kw in q_lower for kw in COMPARE_KEYWORDS) or len(symbols) >= 2:
        return _decide(ROUTE_COMPARE, ["sql_tool", "graph_tool", "news_tool"])

    # 2. Full agent — why/news/today with a single symbol
    if any(kw in q_lower for kw in FULL_AGENT_KEYWORDS):
        return _decide(ROUTE_FULL_AGENT,
                       ["sql_tool", "graph_tool", "news_tool", "vector_tool"])

    # 3. Definitional queries — "what is X", "explain X", "define X"
    #    Only route to vector_only if it's truly educational
    #    (no stock symbol AND no request for live data)
    if is_definitional and not symbols and not wants_data:
        return _decide(ROUTE_VECTOR_ONLY, ["vector_tool"])

    # 4. SQL + Graph — technical analysis, price data
    if any(kw in q_lower for kw in SQL_GRAPH_KEYWORDS):
        return _decide(ROUTE_SQL_GRAPH, ["sql_tool", "graph_tool"])

    # 5. If symbols are present but no keyword matched, default to full_agent
    #    "tell me about NABIL" → should still fetch SQL data + news
    if symbols:
        return _decide(ROUTE_FULL_AGENT,
                       ["sql_tool", "graph_tool", "news_tool"])

    # 6. Vector only — educational, definitional (default, no symbols)
    return _decide(ROUTE_VECTOR_ONLY, ["vector_tool"])

