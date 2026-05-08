"""
Agent API views — Query + Streaming endpoints.

Endpoints:
    POST /api/query/         — Non-streaming full response
    GET  /api/query/stream/  — SSE streaming response
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

# Disclaimer appended to every AI response
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

    # Get or create conversation
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

    # Save user message
    Message.objects.create(
        conversation=convo,
        role='user',
        content=question,
    )

    # Save assistant message
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

    # Update conversation title from first question
    if convo.messages.count() <= 2:
        convo.title = question[:100]
        convo.save(update_fields=['title', 'updated_at'])

    return convo.id


class QueryView(APIView):
    """
    POST /api/query/

    Request body:
        {
            "question": "Why did NABIL fall today?",   (required)
            "symbol": "NABIL",                         (optional)
            "conversation_id": 5                       (optional, for auth users)
        }

    Response: Full JSON response matching API Response Format.
    """

    def post(self, request):
        question = (request.data.get("question") or "").strip()
        symbol = (request.data.get("symbol") or "").strip().upper()
        conversation_id = request.data.get("conversation_id")

        # Validate question
        if not question:
            return Response(
                {"error": "question field is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validate symbol if provided
        if symbol:
            try:
                from services.db_service import verify_symbol_in_neon
                loop = asyncio.new_event_loop()
                try:
                    exists = loop.run_until_complete(
                        verify_symbol_in_neon(symbol)
                    )
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

        # Run agent
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

        # Save to conversation history for authenticated users
        convo_id = _save_messages(
            request, question, symbol, result, conversation_id
        )
        if convo_id:
            result["conversation_id"] = convo_id

        # Check if agent returned an error
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
        data: {"type": "token", "content": "Based"}
        data: {"type": "signals", "data": {...}}
        data: {"type": "citations", "data": [...]}
        data: {"type": "route", "data": "full_agent"}
        data: {"type": "tools", "data": ["sql_tool", ...]}
        data: {"type": "provider", "data": "groq"}
        data: {"type": "done"}
    """

    def get(self, request):
        question = (request.GET.get("question") or "").strip()
        symbol = (request.GET.get("symbol") or "").strip().upper()
        conversation_id = request.GET.get("conversation_id")

        if not question:
            from django.http import JsonResponse
            return JsonResponse(
                {"error": "question parameter is required"},
                status=400,
            )

        response = StreamingHttpResponse(
            self._stream_events(request, question, symbol, conversation_id),
            content_type="text/event-stream",
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response

    def _stream_events(self, request, question, symbol, conversation_id):
        """Generator that yields SSE events."""
        loop = asyncio.new_event_loop()
        try:
            # Run the async streaming logic in the event loop
            async_gen = self._async_stream(
                request, question, symbol, conversation_id
            )
            # Convert async generator to sync
            agen = async_gen.__aiter__()
            while True:
                try:
                    event = loop.run_until_complete(agen.__anext__())
                    yield event
                except StopAsyncIteration:
                    break
        except Exception as e:
            logger.error(
                "SSE stream error: %s", e,
                extra={"event": "sse_stream_error"},
            )
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        finally:
            loop.close()

    async def _async_stream(self, request, question, symbol, conversation_id):
        """Async generator that produces SSE event strings."""
        from services.agent import (
            sql_tool, graph_tool, vector_tool, news_tool,
        )
        from services.query_router import classify_query
        from services.llm_client import stream_llm, build_rag_prompt
        from services.cache_service import (
            get_cached_llm_response, cache_llm_response,
        )

        total_start = time.time()

        # 1. Check cache first
        cached = get_cached_llm_response(question, symbol)
        if cached:
            # Return cached response as a burst of events
            answer = cached.get("answer", "")
            # Send answer in chunks for typewriter effect
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
            yield f"data: {json.dumps({'type': 'provider', 'data': cached.get('llm_provider_used', ''), 'tokens': cached.get('tokens_used', 0)})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            return

        # 2. Route the query
        decision = classify_query(question, symbol)
        route = decision.route
        if not symbol and decision.symbols:
            symbol = decision.symbols[0]

        # 3. Run retrieval tools (non-streaming, fast)
        tools_called = []
        all_citations = []
        signals = {}
        tool_outputs = []

        from services.query_router import (
            ROUTE_VECTOR_ONLY, ROUTE_SQL_GRAPH,
            ROUTE_FULL_AGENT, ROUTE_COMPARE,
        )

        if route in (ROUTE_SQL_GRAPH, ROUTE_FULL_AGENT, ROUTE_COMPARE):
            if symbol:
                sql_text, sql_cites, sql_signals = await sql_tool(symbol)
                if sql_text:
                    tool_outputs.append(sql_text)
                    tools_called.append("sql_tool")
                    all_citations.extend(sql_cites)
                    signals = sql_signals

                graph_text, graph_cites = await graph_tool(question, symbol)
                if graph_text:
                    tool_outputs.append(graph_text)
                    tools_called.append("graph_tool")
                    all_citations.extend(graph_cites)

        if route in (ROUTE_FULL_AGENT, ROUTE_COMPARE):
            if symbol:
                import asyncio as aio
                try:
                    news_text, news_cites = await aio.wait_for(
                        news_tool(symbol), timeout=12.0
                    )
                    if news_text:
                        tool_outputs.append(news_text)
                        tools_called.append("news_tool")
                        all_citations.extend(news_cites)
                except aio.TimeoutError:
                    pass

        if route in (ROUTE_VECTOR_ONLY, ROUTE_FULL_AGENT):
            vec_text, vec_cites = await vector_tool(question)
            if vec_text:
                tool_outputs.append(vec_text)
                tools_called.append("vector_tool")
                all_citations.extend(vec_cites)

        # 4. Send tools/route info before streaming starts
        yield f"data: {json.dumps({'type': 'route', 'data': route})}\n\n"
        yield f"data: {json.dumps({'type': 'tools', 'data': tools_called})}\n\n"

        if signals:
            yield f"data: {json.dumps({'type': 'signals', 'data': signals})}\n\n"

        # 5. Build RAG prompt and stream LLM response
        prompt = build_rag_prompt(question, tool_outputs)
        full_answer = []
        provider_used = "unknown"
        tokens_used = 0

        async for token in stream_llm(prompt):
            if isinstance(token, tuple) and token[0] == "__meta__":
                provider_used = token[1]
                if len(token) > 2:
                    tokens_used = token[2]
                continue
            full_answer.append(token)
            yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"

        answer_text = "".join(full_answer)

        # Ensure disclaimer
        if "DISCLAIMER" not in answer_text:
            disclaimer_token = DISCLAIMER
            yield f"data: {json.dumps({'type': 'token', 'content': disclaimer_token})}\n\n"
            answer_text += disclaimer_token

        # 6. Send citations + provider after streaming
        if all_citations:
            yield f"data: {json.dumps({'type': 'citations', 'data': all_citations})}\n\n"

        yield f"data: {json.dumps({'type': 'provider', 'data': provider_used, 'tokens': tokens_used})}\n\n"

        total_latency = int((time.time() - total_start) * 1000)

        # 7. Cache the full response
        full_response = {
            "answer": answer_text,
            "signals": signals,
            "citations": all_citations,
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

        # 8. Save to conversation history
        _save_messages(request, question, symbol, full_response, conversation_id)

        # 9. Done event
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
