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
        """Async generator that produces SSE event strings."""
        from services.agent import (
            sql_tool, graph_tool, vector_tool, news_tool,
        )
        from services.query_router import classify_query, ROUTE_CHAT
        from services.llm_client import stream_llm, stream_llm_chat, build_rag_prompt, NO_CONTEXT_RESPONSE
        from services.cache_service import (
            get_cached_llm_response, cache_llm_response,
        )

        total_start = time.time()

        # ── 1. Check cache first ──────────────────────────────────────────
        cached = get_cached_llm_response(question, symbol)
        if cached:
            answer = cached.get("answer", "")
            chunk_size = 10
            for i in range(0, len(answer), chunk_size):
                chunk = answer[i:i + chunk_size]
                yield f"data: {json.dumps({'type': 'token', 'content': chunk})}\n\n"

            if cached.get("signals"):
                yield f"data: {json.dumps({'type': 'signals', 'data': cached['signals']})}\n\n"
            if cached.get("citations"):
                yield f"data: {json.dumps({'type': 'citations', 'data': cached['citations']})}\n\n"
            if cached.get("route_used"):
                yield f"data: {json.dumps({'type': 'route', 'data': cached['route_used']})}\n\n"
            if cached.get("tools_called"):
                yield f"data: {json.dumps({'type': 'tools', 'data': cached['tools_called']})}\n\n"
            yield (
                f"data: {json.dumps({'type': 'provider', 'data': cached.get('llm_provider_used', ''), 'tokens': cached.get('tokens_used', 0)})}\n\n"
            )
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            return

        # ── 1.5 Fetch conversation history & Check Redundancy ──────────────
        history_messages = []
        omit_signals = False
        omit_citations = False
        q_lower = (question or "").lower()

        if conversation_id:
            def _fetch_history():
                try:
                    convo_id = int(conversation_id)
                    from apps.accounts.models import Message as DBMessage
                    db_msgs = DBMessage.objects.filter(
                        conversation_id=convo_id
                    ).order_by('-created_at')[:6]
                    res = [{
                        "role": m.role,
                        "content": m.content,
                        "has_signals": bool(m.signals),
                        "has_citations": bool(m.citations)
                    } for m in list(reversed(db_msgs))]
                    return res
                except Exception as e:
                    logger.warning("Failed to fetch conversation history: %s", e)
                    return []

            history_data = await asyncio.to_thread(_fetch_history)
            if history_data:
                for m in history_data:
                    history_messages.append({
                        "role": m["role"],
                        "content": m["content"]
                    })
                
                # Check if we should omit signals/citations to reduce redundancy
                last_assistant = next((m for m in reversed(history_data) if m["role"] == 'assistant'), None)
                if last_assistant:
                    explicit_request = any(w in q_lower for w in [
                        "show", "price", "news", "chart", "table", "indicators", "latest price",
                        "ohlcv", "volume", "rsi", "macd", "ema", "bollinger", "signals", "get news"
                    ])
                    if not explicit_request:
                        omit_signals = True
                        omit_citations = True

        # ── 2. Route the query ────────────────────────────────────────────
        from services.query_router import extract_symbols
        q_symbols = extract_symbols(question)

        # Only use the URL parameter symbol if no symbols were extracted from the question
        if not q_symbols and symbol:
            enriched_question = f"{question} (regarding {symbol})"
            decision = classify_query(enriched_question)
            if not decision.symbols:
                decision.symbols = [symbol]
            question = enriched_question
        else:
            decision = classify_query(question)

        route = decision.route
        all_symbols = list(decision.symbols)

        # ── CHAT short-circuit ────────────────────────────────────
        if route == ROUTE_CHAT:
            full_answer = []
            provider_used = "unknown"
            tokens_used = 0
            async for token in stream_llm_chat(question):
                if isinstance(token, tuple) and token[0] == "__meta__":
                    provider_used = token[1]
                    if len(token) > 2:
                        tokens_used = token[2]
                    continue
                full_answer.append(token)
                yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"
            yield f"data: {json.dumps({'type': 'route', 'data': 'chat'})}\n\n"
            yield f"data: {json.dumps({'type': 'provider', 'data': provider_used, 'tokens': tokens_used})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            return

        # Set the active symbol to the primary symbol queried
        if all_symbols:
            symbol = all_symbols[0]

        from services.query_router import (
            ROUTE_VECTOR_ONLY, ROUTE_SQL_GRAPH,
            ROUTE_FULL_AGENT, ROUTE_COMPARE,
        )

        # ── 3. Run retrieval tools ────────────────────────────────────────
        tools_called = []
        all_citations = []
        all_signals_list = []  # List of signals dicts, one per symbol
        tool_outputs = []

        if route in (ROUTE_SQL_GRAPH, ROUTE_FULL_AGENT, ROUTE_COMPARE):
            # FIX: Iterate ALL symbols, not just the first one from the URL param
            syms_to_fetch = all_symbols if all_symbols else ([symbol] if symbol else [])
            for sym in syms_to_fetch:
                if not sym:
                    continue
                yield f"data: {json.dumps({'type': 'status', 'message': f'Querying database for {sym} price & indicators...'})}\n\n"
                sql_text, sql_cites, sql_signals = await sql_tool(sym)
                if sql_text:
                    tool_outputs.append(sql_text)
                    if "sql_tool" not in tools_called:
                        tools_called.append("sql_tool")
                    all_citations.extend(sql_cites)
                    if sql_signals:
                        all_signals_list.append(sql_signals)

                yield f"data: {json.dumps({'type': 'status', 'message': f'Mapping {sym} sector & peer relationships...'})}\n\n"
                graph_text, graph_cites = await graph_tool(question, sym)
                if graph_text:
                    tool_outputs.append(graph_text)
                    if "graph_tool" not in tools_called:
                        tools_called.append("graph_tool")
                    all_citations.extend(graph_cites)

        if route in (ROUTE_FULL_AGENT, ROUTE_COMPARE):
            # FIX: Fetch news for ALL symbols CONCURRENTLY (not sequentially)
            syms_to_fetch = [s for s in (all_symbols or ([symbol] if symbol else [])) if s]
            if syms_to_fetch:
                syms_label = ", ".join(syms_to_fetch)
                yield f"data: {json.dumps({'type': 'status', 'message': f'Scraping news sources for {syms_label} (ShareSansar, MeroLagani, NepseAlpha, RSS)...'})}\n\n"
                news_results = await asyncio.gather(
                    *[
                        asyncio.wait_for(news_tool(sym), timeout=22.0)
                        for sym in syms_to_fetch
                    ],
                    return_exceptions=True,
                )
                for i, result in enumerate(news_results):
                    sym = syms_to_fetch[i]
                    if isinstance(result, asyncio.TimeoutError):
                        logger.warning(
                            "news_tool(%s): timed out in SSE stream", sym,
                            extra={"event": "news_tool_sse_timeout", "symbol": sym},
                        )
                    elif isinstance(result, Exception):
                        logger.warning(
                            "news_tool(%s) error in SSE stream: %s", sym, result,
                            extra={"event": "news_tool_sse_error", "symbol": sym},
                        )
                    else:
                        news_text, news_cites = result
                        if news_text:
                            tool_outputs.append(news_text)
                            if "news_tool" not in tools_called:
                                tools_called.append("news_tool")
                            all_citations.extend(news_cites)

        # Only run vector_tool if the router included it in tools_needed
        if "vector_tool" in decision.tools_needed:
            yield f"data: {json.dumps({'type': 'status', 'message': 'Searching NEPSE knowledge base for relevant context...'})}\n\n"
            vec_text, vec_cites = await vector_tool(question)
            if vec_text:
                tool_outputs.append(vec_text)
                tools_called.append("vector_tool")
                all_citations.extend(vec_cites)

        # ── 4. Send route + tools before streaming starts ─────────────────
        yield f"data: {json.dumps({'type': 'route', 'data': route})}\n\n"
        yield f"data: {json.dumps({'type': 'tools', 'data': tools_called})}\n\n"

        # Send ALL signals (array for multi-symbol, single dict for single)
        signals_payload = {}
        if all_signals_list:
            signals_payload = all_signals_list if len(all_signals_list) > 1 else all_signals_list[0]
            if not omit_signals:
                yield f"data: {json.dumps({'type': 'signals', 'data': signals_payload})}\n\n"

        if not tool_outputs:
            answer_text = NO_CONTEXT_RESPONSE
            chunk_size = 10
            for i in range(0, len(answer_text), chunk_size):
                chunk = answer_text[i:i + chunk_size]
                yield f"data: {json.dumps({'type': 'token', 'content': chunk})}\n\n"

            total_latency = int((time.time() - total_start) * 1000)

            full_response = {
                "answer": answer_text,
                "signals": [] if omit_signals else signals_payload,
                "citations": [] if omit_citations else all_citations,
                "route_used": route,
                "tools_called": tools_called,
                "latency_ms": total_latency,
                "llm_provider_used": "none",
                "tokens_used": 0,
            }
            try:
                cache_llm_response(question, symbol, full_response, ttl=3600)
            except Exception:
                pass

            await asyncio.to_thread(_save_messages, request, question, symbol, full_response, conversation_id)

            yield f"data: {json.dumps({'type': 'provider', 'data': 'none', 'tokens': 0})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'latency_ms': total_latency})}\n\n"
            return

        # ── 5. Build RAG prompt and stream LLM response ───────────────────
        yield f"data: {json.dumps({'type': 'status', 'message': 'Synthesizing data and generating analysis...'})}\n\n"
        prompt = build_rag_prompt(question, tool_outputs, route=route)
        full_answer = []
        provider_used = "unknown"
        tokens_used = 0
        # Use fewer tokens for single-symbol queries (UI cards show the data)
        llm_max_tokens = 800 if route == ROUTE_COMPARE else 400

        llm_payload = history_messages + [{"role": "user", "content": prompt}] if history_messages else prompt
        async for token in stream_llm(llm_payload, max_tokens=llm_max_tokens):
            if isinstance(token, tuple) and token[0] == "__meta__":
                provider_used = token[1]
                if len(token) > 2:
                    tokens_used = token[2]
                continue
            full_answer.append(token)
            yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"

        answer_text = "".join(full_answer)

        if "DISCLAIMER" not in answer_text:
            disclaimer_token = DISCLAIMER
            yield f"data: {json.dumps({'type': 'token', 'content': disclaimer_token})}\n\n"
            answer_text += disclaimer_token

        # ── 6. Send citations + provider after streaming ──────────────────
        if all_citations and not omit_citations:
            yield f"data: {json.dumps({'type': 'citations', 'data': all_citations})}\n\n"

        yield f"data: {json.dumps({'type': 'provider', 'data': provider_used, 'tokens': tokens_used})}\n\n"

        total_latency = int((time.time() - total_start) * 1000)

        # ── 7. Cache the full response ────────────────────────────────────
        full_response = {
            "answer": answer_text,
            "signals": [] if omit_signals else signals_payload,
            "citations": [] if omit_citations else all_citations,
            "route_used": route,
            "tools_called": tools_called,
            "latency_ms": total_latency,
            "llm_provider_used": provider_used,
            "tokens_used": tokens_used,
        }
        try:
            cache_llm_response(question, symbol, full_response, ttl=3600)
        except Exception:
            pass

        # ── 8. Save to conversation history ───────────────────────────────
        await asyncio.to_thread(_save_messages, request, question, symbol, full_response, conversation_id)

        # ── 9. Done event ─────────────────────────────────────────────────
        yield f"data: {json.dumps({'type': 'done', 'latency_ms': total_latency})}\n\n"

        logger.info(
            "SSE stream complete: route=%s, tools=%s, provider=%s, %dms",
            route, tools_called, provider_used, total_latency,
            extra={
                "event": "sse_query",
                "question": question[:100],
                "symbol": symbol,
                "route": route,
                "latency_ms": total_latency,
            },
        )
