"""
services/agent.py
Agentic RAG service using LangGraph.

Public API:
    run_agent(question, symbol)           -> dict                  (ainvoke, used by POST /api/query/)
    run_agent_streaming(question, symbol) -> AsyncGenerator[dict]  (astream_events v2, used by SSE view)
    sql_tool(symbol, days)                -> (str, list[dict], dict)
    graph_tool(question, symbol)          -> (str, list[dict])
    vector_tool(question)                 -> (str, list[dict])
    news_tool(symbol)                     -> (str, list[dict])
"""

import asyncio
import logging
import time
from typing import TypedDict, AsyncGenerator
from datetime import date as date_cls

from langgraph.graph import StateGraph, END

from services.llm_client import call_llm, build_rag_prompt, NO_CONTEXT_RESPONSE
from services.query_router import (
    classify_query,
    ROUTE_VECTOR_ONLY,
    ROUTE_SQL_GRAPH,
    ROUTE_FULL_AGENT,
    ROUTE_COMPARE,
    MERGED_SYMBOLS_MAP,
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
    question: str
    symbol: str
    symbols: list
    route: str
    sql_output: str
    graph_output: str
    vector_output: str
    news_output: str
    historical_output: str  # NEW
    citations: list
    tools_called: list
    final_answer: str
    llm_provider: str
    tokens_used: int
    latency_ms: int
    signals: list | dict
    price_below: int
    price_above: int
    sector: str
    temporal_params: dict   # NEW
    rank_by_signals: bool



# ══════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════

def _current_month_year() -> str:
    """Returns e.g. 'May 2026' — used in all web search queries."""
    return date_cls.today().strftime("%B %Y")


# ══════════════════════════════════════════════════════════════
# 52-WEEK RANGE — uses execute_neon_query (sync, matches db_service pattern)
# ══════════════════════════════════════════════════════════════

async def _fetch_52w_range(symbol: str) -> dict:
    """
    Queries Neon DB for the true 52-week high/low for a symbol.
    Uses run_in_executor to call the sync execute_neon_query without
    blocking the event loop.
    Returns {"week52_high": float, "week52_low": float} or {} on failure.
    """
    try:
        from services.neon_client import execute_neon_query
        from datetime import timedelta

        cutoff = (date_cls.today() - timedelta(days=365)).isoformat()

        loop = asyncio.get_event_loop()
        rows = await loop.run_in_executor(
            None,
            lambda: execute_neon_query(
                "SELECT MAX(high) AS week52_high, MIN(low) AS week52_low "
                "FROM stocks_stockdata "
                "WHERE symbol = %s AND date >= %s",
                (symbol.upper(), cutoff),
            )
        )

        if rows and rows[0].get("week52_high") is not None:
            return {
                "week52_high": round(float(rows[0]["week52_high"]), 2),
                "week52_low":  round(float(rows[0]["week52_low"]),  2),
            }
        return {}

    except Exception as e:
        logger.warning(
            "_fetch_52w_range(%s) failed: %s", symbol, e,
            extra={"event": "52w_range_error", "symbol": symbol},
        )
        return {}


# ══════════════════════════════════════════════════════════════
# WEB PRICE FALLBACK
# ══════════════════════════════════════════════════════════════

async def _fetch_price_from_web(symbol: str) -> dict | None:
    """
    Fetches latest stock price via web search when Neon DB data is stale.
    Returns {close, source_url} or {raw_text, source_url} or None.
    """
    try:
        from services.web_search import ddg_search
        import re

        query = f'"{symbol}" site:sharesansar.com OR site:merolagani.com OR site:nepalipaisa.com'
        results = await ddg_search(query, count=3)

        if not results:
            return None

        combined = " ".join([
            r.get('snippet', '') + " " + r.get('title', '')
            for r in results[:3]
        ])

        source_url = results[0].get('url', '')

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
                if 100 <= price <= 10000:
                    logger.info(
                        "_fetch_price_from_web(%s): found price %.2f from %s",
                        symbol, price, source_url,
                        extra={"event": "web_price_fetch", "symbol": symbol},
                    )
                    return {'close': price, 'source_url': source_url}

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


# ══════════════════════════════════════════════════════════════
# AGENTIC TOOLS
# ══════════════════════════════════════════════════════════════

async def sql_tool(symbol: str, days: int = 7) -> tuple[str, list[dict], dict]:
    """
    Fetches latest OHLCV + indicators for symbol from Neon DB.
    Supports historical merged symbols transparently.
    Returns: (text_summary, citations, signals_dict)
    On error: ("", [], {})
    """
    if not symbol:
        return "", [], {}

    symbol_upper = symbol.upper()
    active_symbol = MERGED_SYMBOLS_MAP.get(symbol_upper, symbol_upper)
    is_merged = (active_symbol != symbol_upper)

    try:
        from services.db_service import get_latest_ohlcv, get_latest_indicators, get_stock_info, get_recent_history

        ohlcv, indicators, range_52w, recent_history = await asyncio.gather(
            get_latest_ohlcv(active_symbol),
            get_latest_indicators(active_symbol),
            _fetch_52w_range(active_symbol),
            get_recent_history(active_symbol, 10),
        )

        if not ohlcv:
            return "", [], {}

        active_name = active_symbol
        try:
            stock_info = await asyncio.to_thread(get_stock_info, active_symbol)
            if stock_info and stock_info.get("name"):
                active_name = stock_info["name"]
        except Exception:
            pass

        data_date = ohlcv.get('date')
        days_old = 0
        stale_note = ""
        web_source_url = ""

        if data_date:
            try:
                from datetime import datetime
                if isinstance(data_date, str):
                    parsed_date = datetime.strptime(data_date, "%Y-%m-%d").date()
                else:
                    parsed_date = data_date
                days_old = (date_cls.today() - parsed_date).days
            except (ValueError, TypeError):
                pass

        if days_old > 3:
            live = await _fetch_price_from_web(active_symbol)

            if live and live.get('close'):
                ohlcv['close'] = live['close']
                web_source_url = live['source_url']
                stale_note = (
                    f"\n📡 Live price fetched via web search "
                    f"(source: {web_source_url})\n"
                    f"⚠️ Indicators are from {data_date} — {days_old} days old."
                )
            elif live and live.get('raw_text'):
                # Web search found text but no numeric price — use DB data + stale note
                web_source_url = live.get('source_url', '')
                stale_note = (
                    f"\n⚠️ DB indicators are from {data_date} ({days_old} days old). "
                    f"Web search snippet: {live['raw_text'][:200]}"
                )
            else:
                stale_note = (
                    f"\n⚠️ DB data is {days_old} days old (last: {data_date}). "
                    f"Live fetch failed. "
                    f"Check merolagani.com/CompanyDetail.aspx?symbol={active_symbol}"
                )

        close      = ohlcv.get('close') or 0
        high       = ohlcv.get('high') or close
        low        = ohlcv.get('low') or close
        volume     = ohlcv.get('volume') or 0
        date_val   = ohlcv.get('date', 'N/A')

        rsi        = indicators.get('rsi')
        macd       = indicators.get('macd')
        ema_20     = indicators.get('ema_20')
        ema_50     = indicators.get('ema_50')
        bb_upper   = indicators.get('bb_upper')
        bb_lower   = indicators.get('bb_lower')
        bb_middle  = indicators.get('bb_middle')
        vwap       = indicators.get('vwap')
        pct_change = indicators.get('pct_change')

        week52_high = range_52w.get('week52_high') if isinstance(range_52w, dict) else None
        week52_low  = range_52w.get('week52_low')  if isinstance(range_52w, dict) else None

        if rsi is not None:
            if rsi > 70:   rsi_label = "overbought ⚠️"
            elif rsi < 30: rsi_label = "oversold 💡"
            else:          rsi_label = "neutral"
            rsi_text = f"{rsi:.1f} ({rsi_label})"
        else:
            rsi_text = "N/A"

        if macd is not None:
            macd_label = "bullish" if macd > 0 else "bearish"
            macd_text  = f"{macd:.2f} ({macd_label})"
        else:
            macd_text = "N/A"

        pct_text = f"{pct_change:+.1f}%" if pct_change is not None else "N/A"
        vol_text = f"{volume:,}"

        if bb_middle is not None and close:
            bb_position = "near upper band" if close > bb_middle else "near lower band"
        else:
            bb_position = "N/A"

        open_val   = ohlcv.get('open') or close
        
        disp_symbol = f"{symbol_upper} (merged into {active_symbol})" if is_merged else symbol_upper
        
        header = f"{disp_symbol}:" if web_source_url else f"{disp_symbol} as of {date_val}:"
        lines  = [
            header,
            f"SQL DATA: {disp_symbol} — Close: {close:.2f}, Open: {open_val:.2f}, High: {high:.2f}, Low: {low:.2f}, Volume: {vol_text}. Date: {date_val}. Change: {pct_text}.",
            f"Indicators: RSI is {rsi_text}, MACD is {macd_text}.",
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

        citations = [{"type": "db", "symbol": symbol_upper, "date": str(date_val)}]
        if web_source_url:
            citations.append({
                "type": "web",
                "url": web_source_url,
                "description": f"{disp_symbol} live price via web search",
            })

        signals = {
            "symbol": symbol_upper,
            "date": str(date_val),
            "close": close, "high": high, "low": low, "volume": volume,
        }
        if is_merged:
            signals["name"] = f"{active_name} (formerly {symbol_upper})"
            
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

        if recent_history:
            signals["recent_prices"] = [
                round(float(h["close"]), 2)
                for h in sorted(recent_history, key=lambda x: x["date"])
                if h.get("close") is not None
            ]

        logger.info(
            "sql_tool(%s): close=%.1f, rsi=%s",
            symbol_upper, close, rsi_text,
            extra={"event": "sql_tool", "symbol": symbol_upper},
        )
        return text, citations, signals

    except Exception as e:
        logger.warning(
            "sql_tool(%s) failed: %s", symbol, e,
            extra={"event": "sql_tool_error", "symbol": symbol},
        )
        return "", [], {}


async def graph_tool(question: str, symbol: str) -> tuple[str, list[dict]]:
    """Queries graph RAG for sector and peer relationships."""
    if not symbol:
        return "", []

    symbol_upper = symbol.upper()
    active_symbol = MERGED_SYMBOLS_MAP.get(symbol_upper, symbol_upper)
    is_merged = (active_symbol != symbol_upper)

    try:
        from services.graph_rag import query_stock_relationships

        result = query_stock_relationships(active_symbol)

        if not result or not result.get('sector'):
            return "", []

        sector     = result.get('sector', 'Unknown')
        index_name = result.get('index', 'N/A')
        peers      = result.get('peers', [])
        peer_count = result.get('peer_count', 0)

        peer_display = peers[:5]
        peer_text    = ", ".join(peer_display)
        if peer_count > 5:
            peer_text += f" (+{peer_count - 5} more)"

        disp_symbol = f"{symbol_upper} (merged into {active_symbol})" if is_merged else symbol_upper

        text = (
            f"{disp_symbol} — Graph Context:\n"
            f"Sector: {sector}\n"
            f"Index: {index_name}\n"
            f"Sector peers ({peer_count}): {peer_text}"
        )

        citations = [{"type": "graph", "description": f"{disp_symbol}→{sector}→Peers"}]

        logger.info(
            "graph_tool(%s): sector=%s, %d peers",
            symbol_upper, sector, peer_count,
            extra={"event": "graph_tool", "symbol": symbol_upper},
        )
        return text, citations

    except Exception as e:
        logger.warning(
            "graph_tool(%s) failed: %s", symbol, e,
            extra={"event": "graph_tool_error", "symbol": symbol},
        )
        return "", []


async def vector_tool(question: str, extended: bool = False) -> tuple[str, list[dict]]:
    """Retrieves relevant passages from domain knowledge docs.
    
    Args:
        question: User's query.
        extended: If True, retrieves more chunks with larger text for
                  educational/definitional queries (vector_only route).
    """
    if not question:
        return "", []

    try:
        from services.vector_rag import query_vector_rag
        # For educational queries, over-retrieve to cover more content
        retrieve_k = 6 if extended else 3
        results = await asyncio.to_thread(query_vector_rag, question, retrieve_k)

        if not results:
            return "", []

        lines     = []
        citations = []
        max_chunks = 5 if extended else 3
        max_text_len = 1000 if extended else 400

        for chunk in results[:max_chunks]:
            source = chunk.get('source_file', 'unknown')
            text   = chunk.get('text', '')
            if len(text) > max_text_len:
                text = text[:max_text_len] + "..."
            lines.append(f"From {source}:\n{text}")
            citations.append({"type": "vector", "source_file": source})

        text = "\n---\n".join(lines)

        logger.info(
            "vector_tool: %d chunks for '%s' (extended=%s)",
            len(results), question[:50], extended,
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
    Fetches recent news for symbol from the full 8-source pipeline.
    Passes stock_name for better search quality.
    Returns informative fallback when 0 articles found.
    """
    if not symbol:
        return "", []

    symbol_upper = symbol.upper()
    active_symbol = MERGED_SYMBOLS_MAP.get(symbol_upper, symbol_upper)
    is_merged = (active_symbol != symbol_upper)
    search_symbol = active_symbol if active_symbol else symbol_upper

    # Get company name for better DDG search quality
    stock_name = ""
    try:
        from apps.nepse_data.models import Stock
        loop = asyncio.get_event_loop()
        obj = await loop.run_in_executor(
            None,
            lambda: Stock.objects.filter(symbol=search_symbol).first(),
        )
        if obj and obj.name and "auto-created" not in obj.name.lower():
            stock_name = obj.name
    except Exception:
        pass

    try:
        from services.news_scraper import get_news_for_symbol

        articles = await asyncio.wait_for(
            get_news_for_symbol(
                search_symbol,
                stock_name=stock_name,
                max_articles=6,
            ),
            timeout=30.0,
        )

        if not articles:
            fallback_text = (
                f"No recent news found for {symbol_upper} from Nepali financial sources. "
                f"Check ShareSansar or MeroLagani directly for latest announcements."
            )
            logger.info("news_tool(%s): 0 articles found", symbol_upper)
            return fallback_text, []

        disp_symbol = (
            f"{symbol_upper} (merged into {active_symbol})"
            if is_merged else symbol_upper
        )

        lines = [f"Recent news for {disp_symbol}:"]
        citations = []

        for i, article in enumerate(articles[:5], 1):  # up to 5 for LLM context
            headline = article.get("headline") or article.get("title") or "No headline"
            source = article.get("source", "unknown")
            date = article.get("published_date") or article.get("publishedAt") or ""
            url = article.get("url", "")
            body = article.get("body", "")
            summary = article.get("summary", "")

            date_str = f" [{date}]" if date else ""
            content_preview = (body or summary or "").strip()

            if content_preview:
                excerpt = content_preview[:400]
                lines.append(
                    f"{i}. '{headline}' — {source}{date_str}\n"
                    f"   Excerpt: {excerpt}"
                )
            else:
                lines.append(f"{i}. '{headline}' — {source}{date_str}")

            citations.append({
                "type": "news",
                "headline": headline[:200],
                "url": url,
                "source": source,
                "published_at": str(date),
                "summary": (body or summary)[:500],
                "symbol": symbol_upper,
            })

        text = "\n".join(lines)

        logger.info(
            "news_tool(%s): %d articles",
            symbol_upper, len(articles),
            extra={"event": "news_tool", "symbol": symbol_upper, "count": len(articles)},
        )

        return text, citations

    except asyncio.TimeoutError:
        logger.warning(
            "news_tool(%s): timed out after 14s", symbol,
            extra={"event": "news_tool_timeout", "symbol": symbol},
        )
        return "", []

    except Exception as e:
        logger.warning(
            "news_tool(%s) failed: %s", symbol, e,
            extra={"event": "news_tool_error", "symbol": symbol},
        )
        return "", []


async def historical_tool(symbol: str, years_ago: int = None, target_year: int = None) -> tuple[str, list[dict]]:
    """
    Fetches historical price comparison data for symbol.
    Returns: (text_summary, citations)
    """
    if not symbol:
        return "", []

    symbol_upper = symbol.upper()
    active_symbol = MERGED_SYMBOLS_MAP.get(symbol_upper, symbol_upper)

    from services.db_service import get_price_n_years_ago, get_price_at_date
    from datetime import date as date_cls

    # Determine dates
    if years_ago is not None:
        hist_data = await get_price_n_years_ago(active_symbol, years_ago)
        time_period = f"{years_ago} year{'s' if years_ago > 1 else ''} ago"
    elif target_year is not None:
        target_date = f"{target_year}-07-01"  # middle of the year
        hist_data = await get_price_at_date(active_symbol, target_date)
        time_period = f"in {target_year}"
    else:
        # Default to 3 years ago if none provided
        hist_data = await get_price_n_years_ago(active_symbol, 3)
        time_period = "3 years ago"

    # Get current price
    current_data = await get_price_at_date(active_symbol, date_cls.today().strftime("%Y-%m-%d"))

    if not hist_data:
        return f"Historical price comparison for {symbol_upper}: Data not available for {time_period}.", []

    if not current_data:
        # If today is not in DB (e.g. weekend/holiday), fetch latest row overall from DB
        from services.db_service import get_latest_ohlcv
        latest_ohlcv = await get_latest_ohlcv(active_symbol)
        if latest_ohlcv:
            current_data = {
                'symbol': active_symbol,
                'date': latest_ohlcv.get('date'),
                'close': latest_ohlcv.get('close'),
            }

    if not current_data or current_data.get('close') is None:
        return f"Historical price comparison for {symbol_upper}: Could not retrieve current price to perform comparison.", []

    hist_price = hist_data['close']
    curr_price = current_data['close']
    abs_change = curr_price - hist_price
    pct_change = ((curr_price - hist_price) / hist_price * 100) if hist_price else 0
    direction = "increase" if abs_change > 0 else "decrease" if abs_change < 0 else "no change"

    summary_text = (
        f"Historical comparison for {symbol_upper}:\n"
        f"- Historical Date: {hist_data['date']} ({time_period})\n"
        f"- Historical Close: NPR {hist_price:,.2f}\n"
        f"- Current Date: {current_data['date']}\n"
        f"- Current Close: NPR {curr_price:,.2f}\n"
        f"Price change: NPR {abs_change:+,.2f} ({pct_change:+.2f}%) [{direction}]"
    )

    citations = [{
        "type": "historical",
        "symbol": symbol_upper,
        "historical_date": hist_data['date'],
        "historical_price": hist_price,
        "current_date": current_data['date'],
        "current_price": curr_price,
        "pct_change": round(pct_change, 2),
        "direction": direction,
    }]

    return summary_text, citations


# ══════════════════════════════════════════════════════════════
# LANGGRAPH NODES
# ══════════════════════════════════════════════════════════════

async def route_node(state: AgentState) -> dict:
    from services.query_router import extract_symbols
    question = state["question"]
    q_symbols = extract_symbols(question)

    context_symbol = state.get("symbol")
    if q_symbols:
        decision = classify_query(question)
        symbols = q_symbols
    else:
        decision = classify_query(question, context_symbol)
        symbols = decision.symbols

    # Safety net: if symbols is STILL empty but the frontend sent a context
    # symbol (lastSymbol), inject it. This handles follow-ups like
    # "give me news about it" where the pronoun doesn't resolve to a ticker.
    if not symbols and context_symbol:
        symbols = [context_symbol.upper()]
        logger.info(
            "route_node: no symbols found, injecting context symbol '%s'",
            context_symbol,
            extra={"event": "symbol_inject_fallback", "symbol": context_symbol},
        )

    result = {
        "route": decision.route,
        "symbols": symbols,
        "price_below": decision.price_below,
        "price_above": decision.price_above,
        "sector": decision.sector,
        "temporal_params": getattr(decision, "temporal_params", {}),
        "rank_by_signals": getattr(decision, "rank_by_signals", False),
    }
    if symbols:
        result["symbol"] = symbols[0]
    return result


async def sql_node(state: AgentState) -> dict:
    if state.get("route") == 'screener':
        from services.db_service import get_stocks_by_price_filter
        stocks = await asyncio.to_thread(
            get_stocks_by_price_filter,
            sector=state.get("sector"),
            max_price=state.get("price_below"),
            min_price=state.get("price_above"),
            limit=15,
            rank_by_signals=state.get("rank_by_signals", False),
        )
        return {
            "sql_output": stocks,
            "citations": state.get("citations", []),
            "tools_called": state.get("tools_called", []) + ["sql_tool"],
        }

    symbols = state.get("symbols", []) or ([state.get("symbol")] if state.get("symbol") else [])
    if not symbols:
        return {}
    
    all_texts = []
    all_citations = []
    all_signals = []

    for sym in symbols:
        if not sym:
            continue
        text, citations, signals = await sql_tool(sym)
        if text:
            all_texts.append(text)
            all_citations.extend(citations)
            if signals:
                all_signals.append(signals)

    result = {
        "sql_output":   "\n\n".join(all_texts),
        "citations":    state.get("citations", []) + all_citations,
        "tools_called": state.get("tools_called", []) + ["sql_tool"],
    }
    if all_signals:
        result["signals"] = all_signals if len(all_signals) > 1 else all_signals[0]
    return result


async def graph_node(state: AgentState) -> dict:
    symbols = state.get("symbols", []) or ([state.get("symbol")] if state.get("symbol") else [])
    if not symbols:
        return {}
    
    all_texts = []
    all_citations = []

    for sym in symbols:
        if not sym:
            continue
        text, citations = await graph_tool(state["question"], sym)
        if text:
            all_texts.append(text)
            all_citations.extend(citations)

    return {
        "graph_output": "\n\n".join(all_texts),
        "citations":    state.get("citations", []) + all_citations,
        "tools_called": state.get("tools_called", []) + ["graph_tool"],
    }


async def vector_node(state: AgentState) -> dict:
    # Use extended mode for vector_only route (educational queries)
    is_extended = state.get("route") == "vector_only"
    text, citations = await vector_tool(state["question"], extended=is_extended)
    return {
        "vector_output": text,
        "citations":     state.get("citations", []) + citations,
        "tools_called":  state.get("tools_called", []) + ["vector_tool"],
    }


async def news_node(state: AgentState) -> dict:
    symbols = state.get("symbols", []) or ([state.get("symbol")] if state.get("symbol") else [])
    if not symbols:
        return {}
        
    all_texts = []
    all_citations = []

    news_results = await asyncio.gather(
        *[news_tool(sym) for sym in symbols if sym],
        return_exceptions=True
    )

    for i, res in enumerate(news_results):
        if isinstance(res, Exception):
            logger.warning("news_node failed for %s: %s", symbols[i], res)
            continue
        text, citations = res
        if text:
            all_texts.append(text)
            all_citations.extend(citations)

    return {
        "news_output":  "\n\n".join(all_texts),
        "citations":    state.get("citations", []) + all_citations,
        "tools_called": state.get("tools_called", []) + ["news_tool"],
    }


async def _empty_result():
    return "", []


async def _empty_sql_result():
    return "", [], {}


async def parallel_retrieve_node(state: AgentState) -> dict:
    """Full agent / compare: runs tools concurrently for all symbols.
    Skips vector_tool for compare route (no educational docs needed)."""
    symbols = state.get("symbols", []) or ([state.get("symbol")] if state.get("symbol") else [])
    question = state["question"]
    route = state.get("route", "")
    skip_vector = (route == "compare")
    temporal_params = state.get("temporal_params", {})

    tasks = []
    # Gather SQL tasks
    for sym in symbols:
        if sym:
            tasks.append(sql_tool(sym))
    # Gather Graph tasks
    for sym in symbols:
        if sym:
            tasks.append(graph_tool(question, sym))
    # Gather News tasks
    for sym in symbols:
        if sym:
            tasks.append(news_tool(sym))
    # Gather Historical tasks (if temporal intent detected)
    has_temporal = bool(temporal_params)
    if has_temporal:
        for sym in symbols:
            if sym:
                tasks.append(historical_tool(
                    sym,
                    years_ago=temporal_params.get("years_ago"),
                    target_year=temporal_params.get("target_year"),
                ))
    # Gather Vector task (skip for compare route — avoids irrelevant docs)
    if not skip_vector:
        tasks.append(vector_tool(question))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    sql_texts, sql_cites, all_signals = [], [], []
    graph_texts, graph_cites = [], []
    news_texts, news_cites = [], []
    hist_texts, hist_cites = [], []
    vec_text, vec_cites = "", []
    tools_called = []

    idx = 0
    # Parse SQL
    for sym in symbols:
        if sym:
            res = results[idx]
            idx += 1
            if not isinstance(res, Exception):
                text, cites, signals = res
                if text:
                    sql_texts.append(text)
                    sql_cites.extend(cites)
                    if "sql_tool" not in tools_called:
                        tools_called.append("sql_tool")
                    if signals:
                        all_signals.append(signals)
            else:
                logger.warning("parallel sql_tool failed for %s: %s", sym, res)

    # Parse Graph
    for sym in symbols:
        if sym:
            res = results[idx]
            idx += 1
            if not isinstance(res, Exception):
                text, cites = res
                if text:
                    graph_texts.append(text)
                    graph_cites.extend(cites)
                    if "graph_tool" not in tools_called:
                        tools_called.append("graph_tool")
            else:
                logger.warning("parallel graph_tool failed for %s: %s", sym, res)

    # Parse News
    for sym in symbols:
        if sym:
            res = results[idx]
            idx += 1
            if not isinstance(res, Exception):
                text, cites = res
                if text:
                    news_texts.append(text)
                    news_cites.extend(cites)
                    if "news_tool" not in tools_called:
                        tools_called.append("news_tool")
            else:
                logger.warning("parallel news_tool failed for %s: %s", sym, res)

    # Parse Historical
    if has_temporal:
        for sym in symbols:
            if sym:
                res = results[idx]
                idx += 1
                if not isinstance(res, Exception):
                    text, cites = res
                    if text:
                        hist_texts.append(text)
                        hist_cites.extend(cites)
                        if "historical_tool" not in tools_called:
                            tools_called.append("historical_tool")
                else:
                    logger.warning("parallel historical_tool failed for %s: %s", sym, res)

    # Parse Vector (skipped for compare route)
    if not skip_vector and idx < len(results):
        vec_res = results[idx]
        if not isinstance(vec_res, Exception):
            vec_text, vec_cites = vec_res
            if vec_text:
                tools_called.append("vector_tool")
        else:
            logger.warning("parallel vector_tool failed: %s", vec_res)

    all_citations = (
        state.get("citations", [])
        + sql_cites + graph_cites + news_cites + hist_cites + vec_cites
    )

    result = {
        "sql_output":        "\n\n".join(sql_texts),
        "graph_output":      "\n\n".join(graph_texts),
        "vector_output":     vec_text,
        "news_output":       "\n\n".join(news_texts),
        "historical_output": "\n\n".join(hist_texts),
        "citations":         all_citations,
        "tools_called":      state.get("tools_called", []) + tools_called,
    }
    if all_signals:
        result["signals"] = all_signals if len(all_signals) > 1 else all_signals[0]
    return result


async def synthesize_node(state: AgentState) -> dict:
    """
    No-op passthrough — the actual LLM call happens in the SSE view
    (stream_llm) or POST endpoint. This avoids the double-LLM-call
    problem that was burning 2x tokens per query.
    """
    tool_outputs = [
        state.get(k, "")
        for k in ("sql_output", "graph_output", "vector_output", "news_output", "historical_output")
        if state.get(k, "").strip()
    ]

    if not tool_outputs:
        return {
            "final_answer": NO_CONTEXT_RESPONSE,
            "llm_provider": "none",
            "tokens_used": 0,
            "latency_ms": 0,
        }

    # Pass through — LLM will be called by the view layer
    return {
        "final_answer": "",
        "llm_provider": "",
        "tokens_used": 0,
        "latency_ms": 0,
    }


# ══════════════════════════════════════════════════════════════
# LANGGRAPH WORKFLOW
# ══════════════════════════════════════════════════════════════

def _route_decision(state: AgentState) -> str:
    route = state.get("route", ROUTE_VECTOR_ONLY)
    if route == 'screener':
        return "sql_node"
    elif route == ROUTE_VECTOR_ONLY:
        return "vector_node"
    elif route == ROUTE_SQL_GRAPH:
        return "sql_node"
    elif route == ROUTE_COMPARE:
        return "parallel_retrieve_node"
    elif route == ROUTE_FULL_AGENT:
        return "parallel_retrieve_node"
    return "vector_node"


def build_agent_graph():
    graph = StateGraph(AgentState)

    graph.add_node("route_node",             route_node)
    graph.add_node("sql_node",               sql_node)
    graph.add_node("graph_node",             graph_node)
    graph.add_node("vector_node",            vector_node)
    graph.add_node("news_node",              news_node)
    graph.add_node("parallel_retrieve_node", parallel_retrieve_node)
    graph.add_node("synthesize_node",        synthesize_node)

    graph.set_entry_point("route_node")

    graph.add_conditional_edges(
        "route_node",
        _route_decision,
        {
            "vector_node":            "vector_node",
            "sql_node":               "sql_node",
            "parallel_retrieve_node": "parallel_retrieve_node",
        },
    )

    graph.add_edge("vector_node",            "synthesize_node")
    graph.add_edge("sql_node",               "graph_node")
    graph.add_edge("graph_node",             "synthesize_node")
    graph.add_edge("parallel_retrieve_node", "synthesize_node")
    graph.add_edge("synthesize_node",        END)

    return graph.compile()


agent_graph = build_agent_graph()


# ══════════════════════════════════════════════════════════════
# NODE STATUS LABELS  (used by astream_events)
# ══════════════════════════════════════════════════════════════

NODE_STATUS_LABELS: dict[str, str] = {
    "route_node":             "Routing query...",
    "sql_node":               "Querying price & indicator database...",
    "graph_node":             "Mapping sector & peer relationships...",
    "vector_node":            "Searching NEPSE knowledge base...",
    "news_node":              "Scraping live news sources...",
    "parallel_retrieve_node": "Running all data sources in parallel...",
    "synthesize_node":        "Synthesizing analysis with LLM...",
}


# ══════════════════════════════════════════════════════════════
# STREAMING ENTRY POINT  (astream_events v2)
# ══════════════════════════════════════════════════════════════

async def run_agent_streaming(
    question: str,
    symbol: str = "",
) -> AsyncGenerator[dict, None]:
    """
    Streaming entry point for the SSE view.

    Uses LangGraph astream_events(version='v2') so every graph node
    lifecycle fires an event automatically — no manual yield boilerplate.

    Yields dicts matching these shapes:
        {"type": "status",      "message": str}    — node started
        {"type": "node_done",   "node": str}       — node completed
        {"type": "final_state", "state": dict}     — full AgentState after graph finishes

    The caller (SSE view) translates these into SSE events.
    """
    symbol   = (symbol or "").upper().strip()
    question = (question or "").strip()

    if not question:
        return

    initial_state: AgentState = {
        "question": question, "symbol": symbol, "symbols": [],
        "route": "", "sql_output": "", "graph_output": "",
        "vector_output": "", "news_output": "", "historical_output": "",
        "citations": [], "tools_called": [],
        "final_answer": "", "llm_provider": "",
        "latency_ms": 0, "signals": {},
        "tokens_used": 0,
        "price_below": None, "price_above": None, "sector": "",
        "temporal_params": {}, "rank_by_signals": False,
    }

    final_output: dict = {}

    try:
        async for event in agent_graph.astream_events(initial_state, version="v2"):
            kind = event.get("event", "")
            name = event.get("name", "")

            # Node started → emit status
            if kind == "on_chain_start" and name in NODE_STATUS_LABELS:
                yield {"type": "status", "message": NODE_STATUS_LABELS[name]}

            # Node finished → capture final state from synthesize_node
            elif kind == "on_chain_end" and name == "synthesize_node":
                output = event.get("data", {}).get("output", {})
                if output:
                    final_output.update(output)

            # Graph fully finished
            elif kind == "on_chain_end" and name == "LangGraph":
                output = event.get("data", {}).get("output", {})
                if output:
                    final_output.update(output)

    except Exception as e:
        logger.error("run_agent_streaming failed: %s", e,
                     extra={"event": "agent_streaming_error", "symbol": symbol})
        yield {"type": "error", "message": str(e)}
        return

    yield {"type": "final_state", "state": final_output}


# ══════════════════════════════════════════════════════════════
# MAIN ENTRY POINT  (ainvoke — used by POST /api/query/)
# ══════════════════════════════════════════════════════════════

async def run_agent(question: str, symbol: str = "") -> dict:
    """
    Main entry point for the NEPSE AI agent.
    Called by POST /api/query/.
    Runs the LangGraph pipeline then calls LLM once for synthesis.
    """
    symbol   = (symbol or "").upper().strip()
    question = (question or "").strip()

    if not question:
        return {
            "answer": "Please provide a question.",
            "signals": {}, "citations": [], "route_used": "",
            "tools_called": [], "latency_ms": 0,
            "llm_provider_used": "", "debug": {},
        }

    total_start = time.time()

    cached = get_cached_llm_response(question, symbol)
    if cached:
        cached.setdefault("debug", {})["cache_hit"] = True
        logger.info(
            "Agent cache hit: '%s' (symbol=%s)", question[:50], symbol,
            extra={"event": "agent_cache_hit", "symbol": symbol},
        )
        return cached

    initial_state: AgentState = {
        "question": question, "symbol": symbol, "symbols": [],
        "route": "", "sql_output": "", "graph_output": "",
        "vector_output": "", "news_output": "", "historical_output": "",
        "citations": [], "tools_called": [],
        "final_answer": "", "llm_provider": "",
        "latency_ms": 0, "signals": {},
        "tokens_used": 0,
        "price_below": None, "price_above": None, "sector": "",
        "temporal_params": {}, "rank_by_signals": False,
    }

    try:
        final_state = await agent_graph.ainvoke(initial_state)
    except Exception as e:
        total_latency = int((time.time() - total_start) * 1000)
        logger.error("Agent execution failed: %s", e,
                     extra={"event": "agent_error", "symbol": symbol})
        return {
            "answer": (
                f"An error occurred while processing your question: {e}\n\n"
                "DISCLAIMER: This is for educational purposes only. "
                "Not financial advice."
            ),
            "signals": {}, "citations": [],
            "route_used": initial_state.get("route", ""),
            "tools_called": [], "latency_ms": total_latency,
            "llm_provider_used": "", "error": True,
            "debug": {"error": str(e)},
        }

    # ── LLM synthesis (single call — synthesize_node is a passthrough) ──
    tool_outputs = [
        final_state.get(k, "")
        for k in ("sql_output", "graph_output", "vector_output", "news_output", "historical_output")
        if final_state.get(k, "").strip()
    ]

    answer = ""
    provider = "none"
    tokens_used = 0
    llm_latency = 0

    if tool_outputs:
        prompt = build_rag_prompt(
            question, tool_outputs, route=final_state.get("route")
        )
        llm_start = time.time()
        try:
            answer, provider, tokens_used = await call_llm(prompt)
        except RuntimeError as e:
            logger.error("LLM chain exhausted during synthesis: %s", e)
            answer = (
                "I'm sorry, I couldn't generate a response at this time. "
                "All LLM providers are temporarily unavailable.\n\n"
                "DISCLAIMER: This is for educational purposes only. "
                "Not financial advice."
            )
        llm_latency = int((time.time() - llm_start) * 1000)
    else:
        answer = NO_CONTEXT_RESPONSE

    if "DISCLAIMER" not in answer:
        answer += (
            "\n\nDISCLAIMER: This is for educational purposes only. "
            "Not financial advice."
        )

    total_latency = int((time.time() - total_start) * 1000)

    response = {
        "answer":            answer,
        "signals":           final_state.get("signals", {}),
        "citations":         final_state.get("citations", []),
        "route_used":        final_state.get("route", ""),
        "tools_called":      final_state.get("tools_called", []),
        "latency_ms":        total_latency,
        "llm_provider_used": provider,
        "tokens_used":       tokens_used,
        "debug": {
            "cache_hit":      False,
            "llm_latency_ms": llm_latency,
        },
    }

    try:
        cache_llm_response(question, symbol, response, ttl=3600)
    except Exception as e:
        logger.warning("Failed to cache agent response: %s", e)

    logger.info(
        "Agent query complete: route=%s, tools=%s, provider=%s, %dms",
        response["route_used"], response["tools_called"],
        response["llm_provider_used"], total_latency,
        extra={
            "event": "query", "question": question[:100],
            "symbol": symbol, "route": response["route_used"],
            "tools_called": response["tools_called"],
            "llm_provider": response["llm_provider_used"],
            "latency_ms": total_latency, "cache_hit": False,
        },
    )

    return response
