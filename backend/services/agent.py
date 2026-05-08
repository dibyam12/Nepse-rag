"""
Agentic RAG service using LangGraph.

Contains:
    - 4 agentic tools: sql_tool, graph_tool, vector_tool, news_tool
    - LangGraph StateGraph workflow with conditional routing
    - run_agent() entry point for /api/query/

All tools return (text_output: str, citations: list[dict]).
All tools catch errors internally and return ("", []) on failure.

Public API:
    run_agent(question, symbol) -> dict
    sql_tool(symbol, days) -> (str, list[dict])
    graph_tool(question, symbol) -> (str, list[dict])
    vector_tool(question) -> (str, list[dict])
    news_tool(symbol) -> (str, list[dict])
"""

import asyncio
import hashlib
import json
import logging
import time
from typing import TypedDict
from datetime import date as date_cls

from langgraph.graph import StateGraph, END

from services.llm_client import call_llm, build_rag_prompt
from services.query_router import (
    classify_query,
    ROUTE_VECTOR_ONLY,
    ROUTE_SQL_GRAPH,
    ROUTE_FULL_AGENT,
    ROUTE_COMPARE,
)
from services.cache_service import (
    get_cached_llm_response,
    cache_llm_response,
)

logger = logging.getLogger('nepse_rag')


# ══════════════════════════════════════════════════════════════
# AGENT STATE
# ══════════════════════════════════════════════════════════════

class AgentState(TypedDict):
    """State passed through LangGraph nodes."""
    # Input
    question: str
    symbol: str

    # Routing
    route: str

    # Tool outputs (raw text)
    sql_output: str
    graph_output: str
    vector_output: str
    news_output: str

    # Citations (accumulated from all tools)
    citations: list

    # Tracking
    tools_called: list

    # Final output
    final_answer: str
    llm_provider: str
    tokens_used: int
    latency_ms: int
    signals: dict


# ══════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════

def _current_month_year() -> str:
    """Returns e.g. 'May 2026' — used in all web search queries."""
    return date_cls.today().strftime("%B %Y")


# ══════════════════════════════════════════════════════════════
# 52-WEEK RANGE QUERY
# ══════════════════════════════════════════════════════════════

async def _fetch_52w_range(symbol: str) -> dict:
    """
    Queries Neon DB for the true 52-week high/low for a symbol.
    Returns {"week52_high": float, "week52_low": float} or {} on failure.
    """
    try:
        from services.neon_client import get_neon_connection
        from datetime import timedelta

        cutoff = (date_cls.today() - timedelta(days=365)).isoformat()

        async with get_neon_connection() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    MAX(high) AS week52_high,
                    MIN(low)  AS week52_low
                FROM ohlcv
                WHERE symbol = $1
                  AND date   >= $2
                """,
                symbol,
                cutoff,
            )

        if row and row["week52_high"] is not None:
            return {
                "week52_high": round(float(row["week52_high"]), 2),
                "week52_low":  round(float(row["week52_low"]),  2),
            }
        return {}

    except Exception as e:
        logger.warning(
            "_fetch_52w_range(%s) failed: %s", symbol, e,
            extra={"event": "52w_range_error", "symbol": symbol},
        )
        return {}


# ══════════════════════════════════════════════════════════════
# AGENTIC TOOLS
# ══════════════════════════════════════════════════════════════

async def _fetch_price_from_web(symbol: str) -> dict | None:
    """
    Fetches latest stock price via web search when Neon DB data is stale.
    Uses existing web_search service — no HTML scraping.
    Returns {close, source_url} or {raw_text, source_url} or None.
    """
    try:
        from services.web_search import web_search
        import re

        current_month = _current_month_year()
        query = f"{symbol} NEPSE stock price {current_month}"
        results = await web_search(query, count=3)

        if not results:
            return None

        # Combine snippets from top 3 results
        combined = " ".join([
            r.get('snippet', '') + " " + r.get('title', '')
            for r in results[:3]
        ])

        source_url = results[0].get('url', '')

        # Try to extract price from snippet text
        patterns = [
            r'(?:LTP|ltp|close|Close|price|Price)[:\s]+(?:Rs\.?|NPR)?\s*([\d,]+\.?\d*)',
            r'(?:Rs\.?|NPR)\s*([\d,]+\.?\d*)',
            r'\b([\d]{3,4}\.?\d*)\s*(?:NPR|Rs)',
        ]

        for pattern in patterns:
            match = re.search(pattern, combined, re.IGNORECASE)
            if match:
                price_str = match.group(1).replace(',', '')
                price = float(price_str)
                # Sanity check: NEPSE prices are 100-10000 NPR
                if 100 <= price <= 10000:
                    logger.info(
                        "_fetch_price_from_web(%s): found price %.2f from %s",
                        symbol, price, source_url,
                        extra={"event": "web_price_fetch", "symbol": symbol},
                    )
                    return {'close': price, 'source_url': source_url}

        # Regex failed but we have raw text — return it so LLM can read it
        logger.info(
            "_fetch_price_from_web(%s): no price extracted, returning raw snippet",
            symbol,
            extra={"event": "web_price_fetch_raw", "symbol": symbol},
        )
        return {'close': None, 'raw_text': combined[:500], 'source_url': source_url}

    except Exception as e:
        logger.warning(
            "_fetch_price_from_web(%s) failed: %s", symbol, e,
            extra={"event": "web_price_fetch_error", "symbol": symbol},
        )
        return None


async def sql_tool(symbol: str, days: int = 7) -> tuple[str, list[dict], dict]:
    """
    Fetches latest OHLCV + indicators for symbol from Neon DB.

    Returns:
        (text_summary, citations, signals_dict)
        On error: ("", [], {})
    """
    if not symbol:
        return "", [], {}

    try:
        from services.db_service import get_latest_ohlcv, get_latest_indicators

        # Run all three queries concurrently — zero added latency
        ohlcv, indicators, range_52w = await asyncio.gather(
            get_latest_ohlcv(symbol),
            get_latest_indicators(symbol),
            _fetch_52w_range(symbol),
        )

        if not ohlcv:
            return "", [], {}

        # Check if DB data is stale (more than 3 trading days old)
        data_date = ohlcv.get('date')
        days_old = 0
        stale_note = ""
        web_source_url = ""

        if data_date and isinstance(data_date, str):
            try:
                from datetime import datetime
                parsed_date = datetime.strptime(data_date, "%Y-%m-%d").date()
                days_old = (date_cls.today() - parsed_date).days
            except ValueError:
                pass
        elif data_date:
            days_old = (date_cls.today() - data_date).days

        if days_old > 3:
            # DB is stale — fetch live price from web search
            live = await _fetch_price_from_web(symbol)

            if live and live.get('close'):
                ohlcv['close'] = live['close']
                web_source_url = live['source_url']
                stale_note = (
                    f"\n📡 Live price fetched via web search "
                    f"(source: {web_source_url})\n"
                    f"⚠️ Indicators (RSI/MACD/EMA) are from "
                    f"{data_date} — {days_old} days old."
                )

            elif live and live.get('raw_text'):
                text = (
                    f"{symbol} — Latest web search result:\n"
                    f"{live['raw_text']}\n\n"
                    f"Source: {live['source_url']}\n"
                    f"⚠️ DB indicators are from {data_date} "
                    f"({days_old} days old)."
                )
                citations = [
                    {"type": "web", "url": live['source_url'],
                     "description": f"{symbol} live price"},
                    {"type": "db", "symbol": symbol, "date": str(data_date)},
                ]
                return text, citations, {}

            else:
                stale_note = (
                    f"\n⚠️ DB data is {days_old} days old "
                    f"(last: {data_date}). Live fetch failed. "
                    f"Check merolagani.com/CompanyDetail.aspx?symbol={symbol}"
                )

        close  = ohlcv.get('close') or 0
        high   = ohlcv.get('high') or close
        low    = ohlcv.get('low') or close
        volume = ohlcv.get('volume') or 0
        date   = ohlcv.get('date', 'N/A')

        # Extract indicator values (with safe defaults)
        rsi       = indicators.get('rsi')
        macd      = indicators.get('macd')
        ema_20    = indicators.get('ema_20')
        ema_50    = indicators.get('ema_50')
        bb_upper  = indicators.get('bb_upper')
        bb_lower  = indicators.get('bb_lower')
        bb_middle = indicators.get('bb_middle')
        vwap      = indicators.get('vwap')
        pct_change = indicators.get('pct_change')

        week52_high = range_52w.get('week52_high') if isinstance(range_52w, dict) else None
        week52_low  = range_52w.get('week52_low')  if isinstance(range_52w, dict) else None

        # RSI label
        if rsi is not None:
            if rsi > 70:
                rsi_label = "overbought ⚠️"
            elif rsi < 30:
                rsi_label = "oversold 💡"
            else:
                rsi_label = "neutral"
            rsi_text = f"{rsi:.1f} ({rsi_label})"
        else:
            rsi_text = "N/A"

        # MACD label
        if macd is not None:
            macd_label = "bullish" if macd > 0 else "bearish"
            macd_text = f"{macd:.2f} ({macd_label})"
        else:
            macd_text = "N/A"

        # Percent change text
        if pct_change is not None:
            pct_text = f"{pct_change:+.1f}%"
        else:
            pct_text = "N/A"

        vol_text = f"{volume:,}"

        # Bollinger band position
        if bb_middle is not None and close:
            bb_position = "near upper band" if close > bb_middle else "near lower band"
        else:
            bb_position = "N/A"

        # Build text summary (under 200 tokens)
        header = f"{symbol}:" if web_source_url else f"{symbol} as of {date}:"
        lines = [
            header,
            f"Price: Close {close} NPR ({pct_text} vs prev day)",
            f"Volume: {vol_text}",
            f"RSI: {rsi_text}",
            f"MACD: {macd_text}",
        ]
        if ema_20 is not None and ema_50 is not None:
            lines.append(f"EMA-20: {ema_20:.0f} | EMA-50: {ema_50:.0f}")
        if bb_lower is not None and bb_upper is not None:
            lines.append(
                f"Bollinger: {bb_lower:.0f} — {bb_upper:.0f} "
                f"(Price is {bb_position})"
            )
        if week52_high is not None and week52_low is not None:
            lines.append(f"52W Range: {week52_low} — {week52_high} NPR")

        text = "\n".join(lines) + stale_note

        # Build citations
        citations = [{"type": "db", "symbol": symbol, "date": str(date)}]
        if web_source_url:
            citations.append({
                "type": "web",
                "url": web_source_url,
                "description": f"{symbol} live price via web search",
            })

        # Build signals dict for API response
        signals = {
            "close":  close,
            "high":   high,
            "low":    low,
            "volume": volume,
        }
        if rsi        is not None: signals["RSI"]       = round(rsi, 1)
        if macd       is not None: signals["MACD"]      = round(macd, 2)
        if ema_20     is not None: signals["EMA_20"]    = round(ema_20, 1)
        if ema_50     is not None: signals["EMA_50"]    = round(ema_50, 1)
        if bb_upper   is not None: signals["BB_upper"]  = round(bb_upper, 1)
        if bb_middle  is not None: signals["BB_middle"] = round(bb_middle, 1)
        if bb_lower   is not None: signals["BB_lower"]  = round(bb_lower, 1)
        if vwap       is not None: signals["VWAP"]      = round(vwap, 1)
        if pct_change is not None: signals["pct_change"] = round(pct_change, 2)
        if week52_high is not None: signals["week52_high"] = week52_high
        if week52_low  is not None: signals["week52_low"]  = week52_low

        logger.info(
            "sql_tool(%s): close=%.1f, rsi=%s",
            symbol, close, rsi_text,
            extra={"event": "sql_tool", "symbol": symbol},
        )
        return text, citations, signals

    except Exception as e:
        logger.warning(
            "sql_tool(%s) failed: %s", symbol, e,
            extra={"event": "sql_tool_error", "symbol": symbol},
        )
        return "", [], {}


async def graph_tool(question: str, symbol: str) -> tuple[str, list[dict]]:
    """
    Queries graph RAG for sector and peer relationships.

    Returns:
        (text_summary, citations)
        On error: ("", [])
    """
    if not symbol:
        return "", []

    try:
        from services.graph_rag import query_stock_relationships

        result = query_stock_relationships(symbol)

        if not result or not result.get('sector'):
            return "", []

        sector     = result.get('sector', 'Unknown')
        index_name = result.get('index', 'N/A')
        peers      = result.get('peers', [])
        peer_count = result.get('peer_count', 0)

        # Show max 5 peers
        peer_display = peers[:5]
        peer_text = ", ".join(peer_display)
        if peer_count > 5:
            peer_text += f" (+{peer_count - 5} more)"

        lines = [
            f"{symbol} — Graph Context:",
            f"Sector: {sector}",
            f"Index: {index_name}",
            f"Sector peers ({peer_count}): {peer_text}",
        ]

        text = "\n".join(lines)

        citations = [{
            "type": "graph",
            "description": f"{symbol}→{sector}→Peers",
        }]

        logger.info(
            "graph_tool(%s): sector=%s, %d peers",
            symbol, sector, peer_count,
            extra={"event": "graph_tool", "symbol": symbol},
        )
        return text, citations

    except Exception as e:
        logger.warning(
            "graph_tool(%s) failed: %s", symbol, e,
            extra={"event": "graph_tool_error", "symbol": symbol},
        )
        return "", []


async def vector_tool(question: str) -> tuple[str, list[dict]]:
    """
    Retrieves relevant passages from domain knowledge docs.

    Returns:
        (text_summary, citations)
        On error: ("", [])
    """
    if not question:
        return "", []

    try:
        from services.vector_rag import query_vector_rag

        results = query_vector_rag(question, top_k=3)

        if not results:
            return "", []

        lines = []
        citations = []

        for chunk in results[:3]:
            source = chunk.get('source_file', 'unknown')
            text = chunk.get('text', '')

            # Truncate individual chunks to stay within 200 token total
            if len(text) > 400:
                text = text[:400] + "..."

            lines.append(f"From {source}:\n{text}")

            citations.append({
                "type": "vector",
                "source_file": source,
            })

        text = "\n---\n".join(lines)

        logger.info(
            "vector_tool: %d chunks for '%s'",
            len(results), question[:50],
            extra={"event": "vector_tool", "chunks": len(results)},
        )
        return text, citations

    except Exception as e:
        logger.warning(
            "vector_tool failed: %s", e,
            extra={"event": "vector_tool_error"},
        )
        return "", []


async def news_tool(symbol: str) -> tuple[str, list[dict]]:
    """
    Fetches recent news for symbol.

    Returns:
        (text_summary, citations)
        On error: ("", [])
    """
    search_symbol = symbol if symbol else "NEPSE"

    try:
        from services.news_scraper import get_news_for_symbol

        # 12-second timeout for web search
        articles = await asyncio.wait_for(
            get_news_for_symbol(search_symbol, max_articles=5),
            timeout=12.0,
        )

        if not articles:
            return "", []

        lines = [f"Recent news for {symbol}:"]
        citations = []

        for i, article in enumerate(articles[:3], 1):
            headline = article.get('headline', 'No headline')
            source   = article.get('source', 'unknown')
            date     = article.get('published_date', '')
            url      = article.get('url', '')

            date_str = f", {date}" if date else ""
            lines.append(f"{i}. '{headline}' — {source}{date_str}")

            citations.append({
                "type": "news",
                "headline": headline[:200],
                "url": url,
            })

        text = "\n".join(lines)

        logger.info(
            "news_tool(%s): %d articles",
            symbol, len(articles),
            extra={"event": "news_tool", "symbol": symbol,
                   "count": len(articles)},
        )
        return text, citations

    except asyncio.TimeoutError:
        logger.warning(
            "news_tool(%s): timed out after 12s",
            symbol,
            extra={"event": "news_tool_timeout", "symbol": symbol},
        )
        return "", []

    except Exception as e:
        logger.warning(
            "news_tool(%s) failed: %s", symbol, e,
            extra={"event": "news_tool_error", "symbol": symbol},
        )
        return "", []


# ══════════════════════════════════════════════════════════════
# LANGGRAPH NODES
# ══════════════════════════════════════════════════════════════

async def route_node(state: AgentState) -> dict:
    """Step 1: Classify the query and set the route."""
    decision = classify_query(state["question"], state.get("symbol"))
    result = {"route": decision.route}
    if not state.get("symbol") and decision.symbols:
        result["symbol"] = decision.symbols[0]
    return result


async def sql_node(state: AgentState) -> dict:
    """Runs sql_tool for the primary symbol."""
    symbol = state.get("symbol", "")
    if not symbol:
        return {}

    text, citations, signals = await sql_tool(symbol)
    result = {
        "sql_output":   text,
        "citations":    state.get("citations", []) + citations,
        "tools_called": state.get("tools_called", []) + ["sql_tool"],
    }
    if signals:
        result["signals"] = signals
    return result


async def graph_node(state: AgentState) -> dict:
    """Runs graph_tool for the primary symbol."""
    symbol = state.get("symbol", "")
    if not symbol:
        return {}

    text, citations = await graph_tool(state["question"], symbol)
    return {
        "graph_output": text,
        "citations":    state.get("citations", []) + citations,
        "tools_called": state.get("tools_called", []) + ["graph_tool"],
    }


async def vector_node(state: AgentState) -> dict:
    """Runs vector_tool for the question."""
    text, citations = await vector_tool(state["question"])
    return {
        "vector_output": text,
        "citations":     state.get("citations", []) + citations,
        "tools_called":  state.get("tools_called", []) + ["vector_tool"],
    }


async def news_node(state: AgentState) -> dict:
    """Runs news_tool for the primary symbol."""
    symbol = state.get("symbol", "")
    if not symbol:
        return {}

    text, citations = await news_tool(symbol)
    return {
        "news_output":  text,
        "citations":    state.get("citations", []) + citations,
        "tools_called": state.get("tools_called", []) + ["news_tool"],
    }


async def parallel_retrieve_node(state: AgentState) -> dict:
    """
    For full_agent route: runs sql + graph + news tools CONCURRENTLY,
    then runs vector_tool.
    """
    symbol   = state.get("symbol", "")
    question = state["question"]

    # Run sql + graph + news + vector concurrently
    results = await asyncio.gather(
        sql_tool(symbol) if symbol else _empty_sql_result(),
        graph_tool(question, symbol) if symbol else _empty_result(),
        news_tool(symbol),  # news_tool falls back to NEPSE internally
        vector_tool(question),
        return_exceptions=True,
    )

    sql_text, sql_cites, signals = "", [], {}
    graph_text, graph_cites      = "", []
    news_text, news_cites        = "", []
    vec_text, vec_cites          = "", []
    tools_called = []

    # Parse sql_tool result (returns 3-tuple)
    if not isinstance(results[0], Exception):
        sql_text, sql_cites, signals = results[0]
        if sql_text:
            tools_called.append("sql_tool")
    else:
        logger.warning("parallel sql_tool failed: %s", results[0])

    # Parse graph_tool result (returns 2-tuple)
    if not isinstance(results[1], Exception):
        graph_text, graph_cites = results[1]
        if graph_text:
            tools_called.append("graph_tool")
    else:
        logger.warning("parallel graph_tool failed: %s", results[1])

    # Parse news_tool result (returns 2-tuple)
    if not isinstance(results[2], Exception):
        news_text, news_cites = results[2]
        if news_text:
            tools_called.append("news_tool")
    else:
        logger.warning("parallel news_tool failed: %s", results[2])

    # Parse vector_tool result (returns 2-tuple)
    if not isinstance(results[3], Exception):
        vec_text, vec_cites = results[3]
        if vec_text:
            tools_called.append("vector_tool")
    else:
        logger.warning("parallel vector_tool failed: %s", results[3])

    all_citations = (
        state.get("citations", [])
        + sql_cites + graph_cites + news_cites + vec_cites
    )

    result = {
        "sql_output":    sql_text,
        "graph_output":  graph_text,
        "vector_output": vec_text,
        "news_output":   news_text,
        "citations":     all_citations,
        "tools_called":  state.get("tools_called", []) + tools_called,
    }
    if signals:
        result["signals"] = signals

    return result


async def _empty_result():
    """Returns empty 2-tuple for when no symbol is provided."""
    return "", []


async def _empty_sql_result():
    """Returns empty 3-tuple for sql_tool when no symbol is provided."""
    return "", [], {}


async def synthesize_node(state: AgentState) -> dict:
    """
    Final step: Build RAG prompt → call LLM → format answer.
    """
    # Collect all non-empty tool outputs
    tool_outputs = []
    for key in ("sql_output", "graph_output", "vector_output", "news_output"):
        output = state.get(key, "")
        if output and output.strip():
            tool_outputs.append(output)

    # Build RAG prompt
    prompt = build_rag_prompt(state["question"], tool_outputs)

    # Call LLM
    start = time.time()
    try:
        answer, provider, tokens_used = await call_llm(prompt)
    except RuntimeError as e:
        logger.error(
            "LLM chain exhausted during synthesis: %s", e,
            extra={"event": "synthesize_llm_failed"},
        )
        answer = (
            "I'm sorry, I couldn't generate a response at this time. "
            "All LLM providers are temporarily unavailable.\n\n"
            "DISCLAIMER: This is for educational purposes only. "
            "Not financial advice."
        )
        provider = "none"
        tokens_used = 0

    latency_ms = int((time.time() - start) * 1000)

    # Ensure disclaimer is present
    if "DISCLAIMER" not in answer:
        answer += (
            "\n\nDISCLAIMER: This is for educational purposes only. "
            "Not financial advice."
        )

    return {
        "final_answer": answer,
        "llm_provider": provider,
        "tokens_used":  tokens_used,
        "latency_ms":   latency_ms,
    }


# ══════════════════════════════════════════════════════════════
# LANGGRAPH WORKFLOW
# ══════════════════════════════════════════════════════════════

def _route_decision(state: AgentState) -> str:
    """Conditional edge: returns the next node name based on route."""
    route = state.get("route", ROUTE_VECTOR_ONLY)

    if route == ROUTE_VECTOR_ONLY:
        return "vector_node"
    elif route == ROUTE_SQL_GRAPH:
        return "sql_node"
    elif route == ROUTE_COMPARE:
        return "sql_node"
    elif route == ROUTE_FULL_AGENT:
        return "parallel_retrieve_node"
    else:
        return "vector_node"


def build_agent_graph():
    """
    Builds and compiles the LangGraph agent.

    Graph structure:
        route_node
          ├─ vector_only  → vector_node → synthesize_node → END
          ├─ sql_graph    → sql_node → graph_node → synthesize_node → END
          ├─ compare      → sql_node → graph_node → synthesize_node → END
          └─ full_agent   → parallel_retrieve_node → synthesize_node → END

    Returns:
        Compiled StateGraph ready for .ainvoke()
    """
    graph = StateGraph(AgentState)

    # Add all nodes
    graph.add_node("route_node",             route_node)
    graph.add_node("sql_node",               sql_node)
    graph.add_node("graph_node",             graph_node)
    graph.add_node("vector_node",            vector_node)
    graph.add_node("news_node",              news_node)
    graph.add_node("parallel_retrieve_node", parallel_retrieve_node)
    graph.add_node("synthesize_node",        synthesize_node)

    # Entry point
    graph.set_entry_point("route_node")

    # Conditional edges from route_node
    graph.add_conditional_edges(
        "route_node",
        _route_decision,
        {
            "vector_node":            "vector_node",
            "sql_node":               "sql_node",
            "parallel_retrieve_node": "parallel_retrieve_node",
        },
    )

    # Linear edges
    graph.add_edge("vector_node",            "synthesize_node")
    graph.add_edge("sql_node",               "graph_node")
    graph.add_edge("graph_node",             "synthesize_node")
    graph.add_edge("parallel_retrieve_node", "synthesize_node")
    graph.add_edge("synthesize_node",        END)

    return graph.compile()


# Compile at module level (singleton, loaded once)
agent_graph = build_agent_graph()


# ══════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ══════════════════════════════════════════════════════════════

async def run_agent(question: str, symbol: str = "") -> dict:
    """
    Main entry point for the NEPSE AI agent.
    Called by POST /api/query/.

    Steps:
    1. Check LLM response cache → return on hit
    2. Initialize AgentState
    3. Execute LangGraph agent
    4. Build response dict (API Response Format)
    5. Cache response (1h TTL)
    6. Log to JSONL
    7. Return response dict

    Args:
        question: User's natural language question.
        symbol: Optional NEPSE stock symbol (e.g. "NABIL").

    Returns:
        Full response dict matching the API Response Format.
    """
    symbol   = (symbol or "").upper().strip()
    question = (question or "").strip()

    if not question:
        return {
            "answer": "Please provide a question.",
            "signals": {},
            "citations": [],
            "route_used": "",
            "tools_called": [],
            "latency_ms": 0,
            "llm_provider_used": "",
            "debug": {},
        }

    total_start = time.time()

    # 1. Check cache
    cached = get_cached_llm_response(question, symbol)
    if cached:
        cached["debug"] = cached.get("debug", {})
        cached["debug"]["cache_hit"] = True
        logger.info(
            "Agent cache hit: '%s' (symbol=%s)",
            question[:50], symbol,
            extra={"event": "agent_cache_hit", "symbol": symbol},
        )
        return cached

    # 2. Initialize state
    initial_state: AgentState = {
        "question":      question,
        "symbol":        symbol,
        "route":         "",
        "sql_output":    "",
        "graph_output":  "",
        "vector_output": "",
        "news_output":   "",
        "citations":     [],
        "tools_called":  [],
        "final_answer":  "",
        "llm_provider":  "",
        "latency_ms":    0,
        "signals":       {},
    }

    # 3. Execute agent
    try:
        final_state = await agent_graph.ainvoke(initial_state)
    except Exception as e:
        total_latency = int((time.time() - total_start) * 1000)
        logger.error(
            "Agent execution failed: %s", e,
            extra={"event": "agent_error", "symbol": symbol,
                   "latency_ms": total_latency},
        )
        return {
            "answer": (
                f"An error occurred while processing your question: {e}\n\n"
                "DISCLAIMER: This is for educational purposes only. "
                "Not financial advice."
            ),
            "signals": {},
            "citations": [],
            "route_used":        initial_state.get("route", ""),
            "tools_called":      [],
            "latency_ms":        total_latency,
            "llm_provider_used": "",
            "error":             True,
            "debug":             {"error": str(e)},
        }

    total_latency = int((time.time() - total_start) * 1000)

    # 4. Build response dict
    response = {
        "answer":            final_state.get("final_answer", ""),
        "signals":           final_state.get("signals", {}),
        "citations":         final_state.get("citations", []),
        "route_used":        final_state.get("route", ""),
        "tools_called":      final_state.get("tools_called", []),
        "latency_ms":        total_latency,
        "llm_provider_used": final_state.get("llm_provider", ""),
        "debug": {
            "cache_hit":      False,
            "llm_latency_ms": final_state.get("latency_ms", 0),
        },
    }

    # 5. Cache response (1 hour)
    try:
        cache_llm_response(question, symbol, response, ttl=3600)
    except Exception as e:
        logger.warning("Failed to cache agent response: %s", e)

    # 6. Log query
    logger.info(
        "Agent query complete: route=%s, tools=%s, provider=%s, %dms",
        response["route_used"],
        response["tools_called"],
        response["llm_provider_used"],
        total_latency,
        extra={
            "event":        "query",
            "question":     question[:100],
            "symbol":       symbol,
            "route":        response["route_used"],
            "tools_called": response["tools_called"],
            "llm_provider": response["llm_provider_used"],
            "latency_ms":   total_latency,
            "cache_hit":    False,
        },
    )

    return response