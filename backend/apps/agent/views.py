"""
apps/agent/views.py
Agent API views — Query + Streaming endpoints.

Endpoints:
  POST /api/query/        — Non-streaming full response
  GET  /api/query/stream/ — SSE streaming response

FIXES:
  - COMPARE route now iterates ALL extracted symbols (fixes NCCB being ignored)
  - news_tool wrapped in asyncio.wait_for with correct TimeoutError handling
  - Removed bare except Exception that was swallowing TimeoutError silently
"""
import asyncio
import json
import logging
import time

from django.http import StreamingHttpResponse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

logger = logging.getLogger('nepse_rag')

DISCLAIMER = (
    "\n\nDISCLAIMER: This is for educational purposes only. "
    "Not financial advice."
)


def _save_messages(request, question, symbol, result, conversation_id=None):
    """
    Save user + assistant messages to conversation history.
    Only for authenticated users. Creates conversation if needed.
    """
    if not request.user.is_authenticated:
        return None

    from apps.accounts.models import Conversation, Message

    if conversation_id:
        try:
            convo = Conversation.objects.get(
                pk=conversation_id, user=request.user
            )
        except Conversation.DoesNotExist:
            convo = Conversation.objects.create(
                user=request.user,
                title=question[:100],
            )
    else:
        convo = Conversation.objects.create(
            user=request.user,
            title=question[:100],
        )

    Message.objects.create(
        conversation=convo,
        role='user',
        content=question,
    )
    Message.objects.create(
        conversation=convo,
        role='assistant',
        content=result.get('answer', ''),
        signals=result.get('signals'),
        citations=result.get('citations'),
        tools_used=result.get('tools_called'),
        route_used=result.get('route_used', ''),
        llm_provider=result.get('llm_provider_used', ''),
        latency_ms=result.get('latency_ms'),
    )

    if convo.messages.count() <= 2:
        convo.title = question[:100]
        convo.save(update_fields=['title', 'updated_at'])

    return convo.id


def _enrich_signals_with_sector(signals):
    """
    Enriches signals with a fallback sector using SQL data and Graph data.
    """
    if not signals:
        return signals

    from services.db_service import get_stock_info
    from services.graph_rag import query_stock_relationships
    from services.agent import MERGED_SYMBOLS_MAP

    all_signals_list = signals if isinstance(signals, list) else [signals]

    for sig in all_signals_list:
        if isinstance(sig, dict) and sig.get("symbol"):
            sym = sig["symbol"]
            active_symbol = MERGED_SYMBOLS_MAP.get(sym, sym)

            sql_data = {}
            try:
                sql_data = get_stock_info(active_symbol) or {}
            except Exception:
                pass

            graph_data = {}
            try:
                graph_data = query_stock_relationships(active_symbol) or {}
            except Exception:
                pass

            sector = sql_data.get('sector') or graph_data.get('sector') or 'N/A'
            sig["sector"] = sector

    return signals


class QueryView(APIView):
    """
    POST /api/query/

    Request body:
      {
        "question": "Why did NABIL fall today?",  (required)
        "symbol":   "NABIL",                      (optional)
        "conversation_id": 5                      (optional)
      }

    Response: Full JSON response matching API Response Format.
    """

    def post(self, request):
        question = (request.data.get("question") or "").strip()
        symbol = (request.data.get("symbol") or "").strip().upper()
        conversation_id = request.data.get("conversation_id")

        if not question:
            return Response(
                {"error": "question field is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if symbol:
            try:
                from services.db_service import verify_symbol_in_neon
                loop = asyncio.new_event_loop()
                try:
                    exists = loop.run_until_complete(verify_symbol_in_neon(symbol))
                finally:
                    loop.close()
                if not exists:
                    return Response(
                        {"error": f"Symbol {symbol} not found in database"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            except Exception as e:
                logger.warning(
                    "Symbol verification failed for %s: %s", symbol, e,
                    extra={"event": "symbol_verify_error", "symbol": symbol},
                )

        try:
            from services.agent import run_agent
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(run_agent(question, symbol))
            finally:
                loop.close()
        except RuntimeError as e:
            logger.error(
                "Query failed — LLM chain exhausted: %s", e,
                extra={"event": "query_llm_exhausted"},
            )
            return Response(
                {"error": "All LLM providers temporarily unavailable. "
                          "Please try again later."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception as e:
            logger.error(
                "Query failed — unexpected error: %s", e,
                extra={"event": "query_error"},
            )
            return Response(
                {"error": "Internal error", "detail": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        if result.get("signals"):
            result["signals"] = _enrich_signals_with_sector(result["signals"])

        convo_id = _save_messages(
            request, question, symbol, result, conversation_id
        )

        if convo_id:
            result["conversation_id"] = convo_id

        if result.get("error"):
            return Response(result, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        return Response(result, status=status.HTTP_200_OK)


from django.views import View


class StreamQueryView(View):
    """
    GET /api/query/stream/?question=...&symbol=...&conversation_id=...

    SSE streaming endpoint using Django StreamingHttpResponse.
    Streams tokens as they arrive from the LLM.

    Event format:
      data: {"type": "token",     "content": "Based"}
      data: {"type": "signals",   "data": {...}}
      data: {"type": "citations", "data": [...]}
      data: {"type": "route",     "data": "full_agent"}
      data: {"type": "tools",     "data": ["sql_tool", ...]}
      data: {"type": "provider",  "data": "groq"}
      data: {"type": "done"}
    """

    def get(self, request):
        question = (request.GET.get("question") or "").strip()
        symbol = (request.GET.get("symbol") or "").strip().upper()
        conversation_id = request.GET.get("conversation_id")

        if not question:
            from django.http import JsonResponse
            return JsonResponse(
                {"error": "question parameter is required"}, status=400
            )

        response = StreamingHttpResponse(
            self._stream_events(request, question, symbol, conversation_id),
            content_type="text/event-stream",
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response

    def _stream_events(self, request, question, symbol, conversation_id):
        """
        Sync generator that wraps the async generator.
        FIX: loop.shutdown_asyncgens() in finally block prevents
        'Task was destroyed but it is pending!' log noise.
        """
        loop = asyncio.new_event_loop()
        try:
            async_gen = self._async_stream(
                request, question, symbol, conversation_id
            )
            agen = async_gen.__aiter__()
            while True:
                try:
                    event = loop.run_until_complete(agen.__anext__())
                    yield event
                except StopAsyncIteration:
                    break
                except GeneratorExit:
                    # Client disconnected — cancel pending tasks cleanly
                    loop.run_until_complete(async_gen.aclose())
                    break
                except Exception as e:
                    logger.error(
                        "SSE stream error: %s", e,
                        extra={"event": "sse_stream_error"},
                    )
                    yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
                    yield f"data: {json.dumps({'type': 'done'})}\n\n"
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                pass
            loop.close()

    async def _async_stream(self, request, question, symbol, conversation_id):
        """
        Async generator that produces SSE event strings.

        Architecture:
          - Cache hits:          replay tokens directly (no graph)
          - CHAT route:          stream_llm_chat (no graph)
          - Screener route:      direct db call (no graph)
          - All other routes:    run_agent_streaming() → astream_events v2
                                 The graph emits status events automatically
                                 as each node executes, then we stream the
                                 LLM answer from final_state via stream_llm.
        """
        from services.agent import run_agent_streaming
        from services.query_router import classify_query, ROUTE_CHAT, extract_symbols
        from services.llm_client import (
            stream_llm, stream_llm_chat, build_rag_prompt,
            NO_CONTEXT_RESPONSE, PROVIDERS,
        )
        from services.golden_matcher import match_golden
        from services.cache_service import (
            get_cached_llm_response, cache_llm_response, is_llm_provider_exhausted,
        )
        from decouple import config as _decouple_config

        total_start = time.time()

        # ── 1. Check cache ────────────────────────────────────────────────
        cached = get_cached_llm_response(question, symbol)
        if cached:
            answer = cached.get("answer", "")
            chunk_size = 10
            for i in range(0, len(answer), chunk_size):
                yield f"data: {json.dumps({'type': 'token', 'content': answer[i:i+chunk_size]})}\n\n"
            if cached.get("signals"):
                yield f"data: {json.dumps({'type': 'signals', 'data': cached['signals']})}\n\n"
            if cached.get("citations"):
                yield f"data: {json.dumps({'type': 'citations', 'data': cached['citations']})}\n\n"
            if cached.get("route_used"):
                yield f"data: {json.dumps({'type': 'route', 'data': cached['route_used']})}\n\n"
            if cached.get("tools_called"):
                yield f"data: {json.dumps({'type': 'tools', 'data': cached['tools_called']})}\n\n"
            yield f"data: {json.dumps({'type': 'provider', 'data': cached.get('llm_provider_used', ''), 'tokens': cached.get('tokens_used', 0)})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            return

        # ── 1.5 Fetch conversation history & check redundancy ─────────────
        history = []
        omit_signals = False
        omit_citations = False
        q_lower = (question or "").lower()

        is_followup = request.GET.get("is_followup", "false") == "true"
        if is_followup:
            explicit_request = any(w in q_lower for w in [
                "show", "price", "news", "chart", "table", "indicators", "latest price",
                "ohlcv", "volume", "rsi", "macd", "ema", "bollinger", "signals", "get news",
                "compare", "vs", "history", "historical"
            ])
            if not explicit_request:
                omit_signals = True
                omit_citations = True

        if conversation_id:
            def _fetch_history():
                try:
                    convo_id = int(conversation_id)
                    from apps.accounts.models import Message as DBMessage
                    db_msgs = DBMessage.objects.filter(
                        conversation_id=convo_id
                    ).order_by('-created_at')[:6]
                    return list(reversed(db_msgs))
                except Exception as e:
                    logger.warning("Failed to fetch conversation history: %s", e)
                    return []

            history_data = await asyncio.to_thread(_fetch_history)
            if history_data:
                for m in history_data:
                    trunc_len = 600 if m.role == 'assistant' else 400
                    history.append({
                        "role": m.role,
                        "content": (m.content or "")[:trunc_len],
                        "has_signals": bool(getattr(m, "signals", None)),
                        "has_citations": bool(getattr(m, "citations", None)),
                    })
                if not is_followup:
                    last_assistant = next((m for m in reversed(history_data) if m.role == 'assistant'), None)
                    if last_assistant:
                        explicit_request = any(w in q_lower for w in [
                            "show", "price", "news", "chart", "table", "indicators", "latest price",
                            "ohlcv", "volume", "rsi", "macd", "ema", "bollinger", "signals", "get news",
                            "compare", "vs", "history", "historical"
                        ])
                        if not explicit_request:
                            omit_signals = True
                            omit_citations = True

        # ── 2. Classify query ─────────────────────────────────────────────
        q_symbols = extract_symbols(question)

        # If no symbols in current question, try to recover from conversation history
        # This handles follow-ups like "give me news about them" after comparing NICA+NCCB
        if not q_symbols and history:
            history_symbols = []
            seen_syms = set()
            for msg in reversed(history):
                if msg.get("role") == "user":
                    msg_syms = extract_symbols(msg.get("content", ""))
                    for s in msg_syms:
                        if s not in seen_syms:
                            seen_syms.add(s)
                            history_symbols.append(s)
                    if history_symbols:
                        break  # use symbols from most recent user message that had them
            if history_symbols:
                q_symbols = history_symbols

        from services.query_router import ROUTE_VECTOR_ONLY, ROUTE_SQL_GRAPH, ROUTE_FULL_AGENT, ROUTE_COMPARE
        if not q_symbols and symbol:
            # Guard: classify the raw question first. If it's chat or pure educational
            # (no stock keywords), don't inject the context symbol — this prevents
            # off-topic questions like "height of mount everest" from being treated
            # as a stock query just because the frontend sent lastSymbol.
            raw_decision = classify_query(question)
            _STOCK_HINT_WORDS = {
                'price', 'news', 'buy', 'sell', 'stock', 'share', 'indicator',
                'rsi', 'macd', 'ema', 'volume', 'sector', 'analysis', 'about it',
                'about them', 'about this', 'fundamentals', 'compare', 'chart',
                'history', 'historical',
            }
            has_stock_hint = any(w in q_lower for w in _STOCK_HINT_WORDS)
            
            if raw_decision.route in (ROUTE_CHAT,) or (raw_decision.route == ROUTE_VECTOR_ONLY and not has_stock_hint):
                # Off-topic or purely educational — don't inject stock symbol
                decision = raw_decision
            else:
                enriched_question = f"{question} (regarding {symbol})"
                decision = classify_query(enriched_question)
                if not decision.symbols:
                    decision.symbols = [symbol]
                question = enriched_question
        elif q_symbols:
            # Inject recovered symbols into the question for proper routing
            sym_str = " ".join(q_symbols)
            enriched_question = f"{question} (regarding {sym_str})"
            decision = classify_query(enriched_question)
            if not decision.symbols:
                decision.symbols = q_symbols
            question = enriched_question
        else:
            decision = classify_query(question)

        route = decision.route
        all_symbols = list(decision.symbols)
        if all_symbols:
            symbol = all_symbols[0]
            yield f"data: {json.dumps({'type': 'active_symbols', 'data': all_symbols})}\n\n"

        # ── Golden prompt detection ───────────────────────────────────────
        golden_match = match_golden(question, all_symbols)
        if golden_match:
            logger.info("Golden prompt matched: %s", golden_match["id"])

        _ROUTE_LABELS = {
            'full_agent':  'Full Agent (SQL + Graph + News + Vector)',
            'sql_graph':   'SQL + Graph retrieval',
            'compare':     'Multi-symbol comparison',
            'vector_only': 'Knowledge base search',
            'screener':    'Stock screener',
            'chat':        'Chat',
        }
        yield f"data: {json.dumps({'type': 'status', 'message': f'Query classified → {_ROUTE_LABELS.get(route, route)}' })}\n\n"

        # ── CHAT short-circuit (bypasses graph) ───────────────────────────
        if route == ROUTE_CHAT:
            full_answer = []
            provider_used = "unknown"
            tokens_used = 0
            async for token in stream_llm_chat(question):
                if isinstance(token, tuple) and token[0] == "__meta__":
                    provider_used = token[1]
                    tokens_used = token[2] if len(token) > 2 else 0
                    continue
                full_answer.append(token)
                yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"
            yield f"data: {json.dumps({'type': 'route', 'data': 'chat'})}\n\n"
            yield f"data: {json.dumps({'type': 'provider', 'data': provider_used, 'tokens': tokens_used})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            return

        # ── SCREENER short-circuit (bypasses graph) ───────────────────────
        if route == 'screener':
            # Clear history for screener queries — screener results should
            # never pollute follow-up context or inject spurious symbols
            history = []
            from services.agent import sql_tool, graph_tool, vector_tool, news_tool
            from services.query_router import ROUTE_VECTOR_ONLY, ROUTE_SQL_GRAPH, ROUTE_FULL_AGENT, ROUTE_COMPARE
            yield f"data: {json.dumps({'type': 'status', 'message': 'Running stock screener query...'})}\n\n"
            from services.db_service import get_stocks_by_price_filter
            stocks = await asyncio.to_thread(
                get_stocks_by_price_filter,
                sector=decision.sector,
                max_price=decision.price_below,
                min_price=decision.price_above,
                limit=8,
            )
            tool_outputs = [stocks]
            tools_called = ["sql_tool"]
            all_citations = []
            signals_payload = {}

            yield f"data: {json.dumps({'type': 'route', 'data': route})}\n\n"
            yield f"data: {json.dumps({'type': 'tools', 'data': tools_called})}\n\n"

            source_count = len(tool_outputs)
            yield f"data: {json.dumps({'type': 'status', 'message': f'{source_count} data source(s) gathered — building context window...'})}\n\n"
            for _p in PROVIDERS:
                _key = _decouple_config(_p["api_key_env"], default="") if _p["api_key_env"] else "local"
                if _key and not is_llm_provider_exhausted(_p["name"]):
                    _pname = _p["name"]
                    yield f"data: {json.dumps({'type': 'status', 'message': f'Generating analysis via {_pname}...'})}\n\n"
                    break

            prompt = build_rag_prompt(question, tool_outputs, route=route, history=history, golden_match=golden_match)
            full_answer = []
            provider_used = "unknown"
            tokens_used = 0
            llm_max_tokens = 400
            async for token in stream_llm(prompt, max_tokens=llm_max_tokens):
                if isinstance(token, tuple) and token[0] == "__meta__":
                    provider_used = token[1]
                    tokens_used = token[2] if len(token) > 2 else 0
                    continue
                full_answer.append(token)
                yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"

            answer_text = "".join(full_answer)
            if "DISCLAIMER" not in answer_text:
                answer_text += DISCLAIMER
                yield f"data: {json.dumps({'type': 'token', 'content': DISCLAIMER})}\n\n"

            total_latency = int((time.time() - total_start) * 1000)
            yield f"data: {json.dumps({'type': 'provider', 'data': provider_used, 'tokens': tokens_used})}\n\n"

            full_response = {
                "answer": answer_text, "signals": signals_payload,
                "citations": all_citations, "route_used": route,
                "tools_called": tools_called, "latency_ms": total_latency,
                "llm_provider_used": provider_used, "tokens_used": tokens_used,
            }
            try:
                cache_llm_response(question, symbol, full_response, ttl=3600)
            except Exception:
                pass
            await asyncio.to_thread(_save_messages, request, question, symbol, full_response, conversation_id)
            yield f"data: {json.dumps({'type': 'done', 'latency_ms': total_latency})}\n\n"
            return

        # ── 3. MAIN PATH: run_agent_streaming via astream_events v2 ──────
        from services.query_router import ROUTE_VECTOR_ONLY, ROUTE_SQL_GRAPH, ROUTE_FULL_AGENT, ROUTE_COMPARE

        final_state: dict = {}
        emitted_statuses: set = set()

        async for agent_event in run_agent_streaming(question, symbol):
            etype = agent_event.get("type")

            if etype == "status":
                msg = agent_event["message"]
                # Deduplicate status messages
                if msg not in emitted_statuses:
                    emitted_statuses.add(msg)
                    yield f"data: {json.dumps({'type': 'status', 'message': msg})}\n\n"

            elif etype == "final_state":
                final_state = agent_event.get("state", {})

            elif etype == "error":
                yield f"data: {json.dumps({'type': 'error', 'message': agent_event.get('message', 'Agent error')})}\n\n"
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
                return

        # ── 4. Extract data from final state ──────────────────────────────
        route_used    = final_state.get("route", route)
        tools_called  = final_state.get("tools_called", [])
        all_citations = final_state.get("citations", [])

        raw_signals = final_state.get("signals", {})
        all_signals_list = raw_signals if isinstance(raw_signals, list) else ([raw_signals] if raw_signals else [])
        signals_payload  = all_signals_list if len(all_signals_list) > 1 else (all_signals_list[0] if all_signals_list else {})

        if signals_payload:
            signals_payload = _enrich_signals_with_sector(signals_payload)

        yield f"data: {json.dumps({'type': 'route', 'data': route_used})}\n\n"
        yield f"data: {json.dumps({'type': 'tools', 'data': tools_called})}\n\n"
        if signals_payload and not omit_signals:
            yield f"data: {json.dumps({'type': 'signals', 'data': signals_payload})}\n\n"
            if isinstance(signals_payload, dict) and signals_payload.get("symbol"):
                pass  # lastSymbol set on frontend via signals.symbol

        # ── 5. Stream LLM answer from final state ─────────────────────────
        # The graph's synthesize_node already called the LLM (non-streaming).
        # We replay the stored answer as tokens for the typewriter effect.
        # For the best UX, we re-stream using stream_llm over the same prompt.
        tool_outputs = [
            final_state.get(k, "")
            for k in ("sql_output", "graph_output", "vector_output", "news_output", "historical_output")
            if final_state.get(k, "").strip()
        ]

        full_answer = []
        provider_used = "unknown"
        tokens_used = 0

        if tool_outputs:
            source_count = len(tool_outputs)
            yield f"data: {json.dumps({'type': 'status', 'message': f'{source_count} data source(s) gathered — building context window...'})}\n\n"

            # Show which provider we'll use
            for _p in PROVIDERS:
                _key = _decouple_config(_p["api_key_env"], default="") if _p["api_key_env"] else "local"
                if _key and not is_llm_provider_exhausted(_p["name"]):
                    _pname = _p["name"]
                    yield f"data: {json.dumps({'type': 'status', 'message': f'Generating analysis via {_pname}...'})}\n\n"
                    break

            prompt = build_rag_prompt(question, tool_outputs, route=route_used, history=history, golden_match=golden_match)
            llm_max_tokens = 800 if route_used == ROUTE_COMPARE else 400

            async for token in stream_llm(prompt, max_tokens=llm_max_tokens):
                if isinstance(token, tuple) and token[0] == "__meta__":
                    provider_used = token[1]
                    tokens_used = token[2] if len(token) > 2 else 0
                    continue
                full_answer.append(token)
                yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"
        else:
            # No context — replay NO_CONTEXT_RESPONSE as tokens
            chunk_size = 10
            for i in range(0, len(NO_CONTEXT_RESPONSE), chunk_size):
                chunk = NO_CONTEXT_RESPONSE[i:i+chunk_size]
                full_answer.append(chunk)
                yield f"data: {json.dumps({'type': 'token', 'content': chunk})}\n\n"

        answer_text = "".join(full_answer)
        if "DISCLAIMER" not in answer_text:
            answer_text += DISCLAIMER
            yield f"data: {json.dumps({'type': 'token', 'content': DISCLAIMER})}\n\n"

        # ── 5.5. Groundedness check (best-effort, non-blocking) ───────────
        try:
            from services.groundedness import check_groundedness
            context_chunks = [
                final_state.get(k, "")
                for k in ("sql_output", "graph_output", "vector_output", "news_output", "historical_output")
                if final_state.get(k, "").strip()
            ]
            if context_chunks:
                g_result = await asyncio.to_thread(
                    check_groundedness, answer_text, context_chunks
                )
                # NOTE: ms-marco cross-encoder is a relevance model, not an
                # entailment model. Analytical prose about raw data always scores
                # low, causing false-positive warnings on every response.
                # We log the score for RAGAS evaluation but no longer display
                # the warning to users.
                # if g_result.score < 0.3:
                #     grounding_note = (...)
                #     yield grounding_note

                logger.info(
                    "Groundedness score for '%s': %.2f (%d flagged / %d total)",
                    question[:50], g_result.score,
                    len(g_result.flagged_claims), g_result.total_claims,
                )
        except Exception as e:
            logger.warning("Groundedness check failed (non-fatal): %s", e)

        # ── 6. Send citations + metadata ──────────────────────────────────
        if all_citations and not omit_citations:
            yield f"data: {json.dumps({'type': 'citations', 'data': all_citations})}\n\n"

        yield f"data: {json.dumps({'type': 'provider', 'data': provider_used, 'tokens': tokens_used})}\n\n"

        total_latency = int((time.time() - total_start) * 1000)

        # ── 7. Cache + save ───────────────────────────────────────────────
        full_response = {
            "answer": answer_text,
            "signals": {} if omit_signals else signals_payload,
            "citations": [] if omit_citations else all_citations,
            "route_used": route_used,
            "tools_called": tools_called,
            "latency_ms": total_latency,
            "llm_provider_used": provider_used,
            "tokens_used": tokens_used,
        }
        try:
            cache_llm_response(question, symbol, full_response, ttl=3600)
        except Exception:
            pass
        await asyncio.to_thread(_save_messages, request, question, symbol, full_response, conversation_id)

        # ── 8. Done ───────────────────────────────────────────────────────
        yield f"data: {json.dumps({'type': 'done', 'latency_ms': total_latency})}\n\n"

        logger.info(
            "SSE stream complete: route=%s, tools=%s, provider=%s, %dms",
            route_used, tools_called, provider_used, total_latency,
            extra={
                "event": "sse_query",
                "question": question[:100],
                "symbol": symbol,
                "route": route_used,
                "latency_ms": total_latency,
            },
        )

