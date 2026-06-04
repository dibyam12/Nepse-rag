"""
LLM Client with 4-provider fallback chain.

Provider priority:
    1. Groq        — llama-3.1-8b-instant   (fastest, free 500K tokens/day)
    2. Google AI   — gemini-2.5-flash        (best quality, free 1.5M/day)
    3. OpenRouter  — llama-3.2-3b:free       (fallback, 50K/day)
    4. Ollama      — llama3.2:3b             (local offline, unlimited)

All providers use OpenAI-compatible /chat/completions format.

Public API:
    call_llm(prompt, max_tokens) -> (answer, provider_name, tokens_used)
    build_rag_prompt(question, tool_outputs, max_input_tokens) -> str
    stream_llm(prompt) -> AsyncGenerator[str, None]
"""

import logging
import time
from typing import AsyncGenerator

import httpx
from decouple import config

from services.cache_service import (
    is_llm_provider_exhausted,
    mark_llm_provider_exhausted,
    track_llm_tokens,
)

logger = logging.getLogger('nepse_rag')

# ── System Prompt (prepended to every LLM call) ──────────────
SYSTEM_PROMPT = (
    "You are a NEPSE (Nepal Stock Exchange) AI research assistant. "
    "Respond like a premium Bloomberg terminal — direct, data-driven, zero fluff.\n\n"
    "## ANTI-HALLUCINATION RULES:\n"
    "1. You are operating in CLOSED-BOOK mode. You have NO knowledge beyond what is in the <context> block.\n"
    "2. If a number, price, date, or percentage is NOT in the context, say 'Data not available in current context.'\n"
    "3. If asked about a stock NOT in the context, say 'I don't have data for [SYMBOL] right now. Try querying it directly.'\n"
    "4. NEVER extrapolate or calculate values not explicitly given (e.g., don't compute P/E ratio from fragments).\n"
    "5. For news: ONLY summarize headlines/content that appear in <news_data>. DO NOT add news from your training data.\n"
    "6. When uncertain, use hedging language: 'Based on the available data...' rather than asserting facts.\n\n"
    "## MANDATORY Rules (violating ANY of these is UNACCEPTABLE):\n"
    "1. You MUST start your response with a `<thinking>` block to write your step-by-step reasoning. "
    "Close it with `</thinking>` before starting your final analysis. In the thinking block (Chain-of-Verification):\n"
    "   - Identify the user's question and the active symbols queried.\n"
    "   - Locate the structured data blocks in the context (e.g., `<sql_data>`, `<news_data>`).\n"
    "   - List the numbers and headlines you will use, verifying they are exactly as listed in the context.\n"
    "   - For each fact you plan to state, write [VERIFIED: <source_tag>] or [NOT FOUND].\n"
    "   - If any fact is [NOT FOUND], explicitly plan to say 'data not available'.\n"
    "   - If any symbol requested is missing data, explicitly note that and plan to address it in the response (e.g., NCCB is merged into KBL).\n"
    "2. Each 'SQL DATA:' block in the context IS the stock's current price. "
    "State the close value as the latest price. "
    "NEVER say 'no price data' or 'limited information' if SQL DATA exists for that symbol.\n"
    "3. If there are SQL DATA blocks for MULTIPLE symbols (e.g., NABIL and NICA), "
    "you MUST present price data for ALL of them. Skipping ANY symbol's data is WRONG.\n"
    "4. DO NOT explain what indicators mean. No definitions. No theory. "
    "Wrong: 'RSI is a momentum indicator that measures...' "
    "Right: 'RSI: 51.0 — neutral' "
    "Only explain if user says 'what is RSI' or 'explain MACD'.\n"
    "5. STRICT GROUNDING: NEVER invent prices, indicators, news, or URLs not in the context. "
    "If information is missing, state 'I do not have access to that information in my current database context.' rather than guessing or fabricating.\n"
    "6. For news: if only a headline exists with no summary, just show the headline "
    "and source. NEVER write '[context unclear]', '[no context]', or similar placeholders.\n"
    "7. The UI already shows a PriceCard with LTP/Volume/Range and a SignalsTable "
    "with RSI/MACD/EMA/BB. Do NOT repeat these exact numbers in your text. "
    "Instead, provide a brief 1-2 sentence ANALYSIS or commentary on what the data means "
    "for the stock (e.g., 'NABIL is trading near its 52-week high with neutral momentum').\n"
    "8. CONVERSATIONAL MEMORY: You will receive the conversation history. "
    "Do NOT repeat descriptions, indicators, news summaries, or comparisons if they were already stated in the previous turns. "
    "If the user asks a follow-up or comparison decision (e.g., 'should I buy X or Y?', 'so should I go with X?'), "
    "directly analyze the options based on the previously stated facts and your RAG context. "
    "Focus on answering the new question directly. "
    "Acknowledge the user's follow-up naturally (e.g., 'Given that...', 'As mentioned...') without repeating the stock profiles or news headlines from the previous turns.\n\n"
    "## EXAMPLE of a GOOD response:\n"
    "<example>\n"
    "<thinking>\n"
    "Question: Compare NABIL and NICA fundamentals.\n"
    "Active Symbols: NABIL, NICA.\n"
    "SQL Data: NABIL close=350.50 [VERIFIED: sql_data], NICA close=366.30 [VERIFIED: sql_data].\n"
    "RSI: NABIL=58.2 (neutral) [VERIFIED: sql_data], NICA=51.0 (neutral) [VERIFIED: sql_data].\n"
    "News: NICA resignation [VERIFIED: news_data], NABIL no news [VERIFIED: news_data].\n"
    "Plan: Synthesize both prices, indicators, and news without listing raw numbers. Note NICA's news.\n"
    "</thinking>\n\n"
    "**Price & Trend**: Both NABIL and NICA are displaying neutral momentum, with both stocks currently consolidating.\n\n"
    "**News**: NICA has news regarding capital restructuring and director changes. No recent news is available for NABIL.\n\n"
    "**Comparison**: NABIL is trading at a slightly lower price point than NICA, with both banks exhibiting similar neutral indicators.\n\n"
    "DISCLAIMER: This is for educational purposes only. Not financial advice.\n"
    "</example>\n\n"
    "## Output Structure:\n"
    "Start immediately with `<thinking>\n[Your step-by-step analytical reasoning and fact verification]\n</thinking>`\n\n"
    "Then provide the synthesis:\n"
    "- **Price & Trend**: Provide a 1-2 sentence analysis combining price action and indicator momentum.\n"
    "- **News**: If news exists, summarize the overall sentiment in 1 sentence. DO NOT list individual news articles (the UI shows them).\n"
    "- **Comparison**: ONLY if there are multiple stocks in the context, provide a brief comparison of their performance.\n\n"
    "Always end with: \n\nDISCLAIMER: This is for educational purposes only. Not financial advice."
)

NO_CONTEXT_RESPONSE = (
    "I can answer NEPSE-related questions about listed stocks, indicators, sectors, and market news. "
    "Please ask about a NEPSE company or indicator (e.g., 'Why did NABIL fall today?' or 'What is RSI?')."
    "\n\nDISCLAIMER: This is for educational purposes only. Not financial advice."
)

CHAT_SYSTEM_PROMPT = (
    "You are NEPSE AI, a friendly and knowledgeable research assistant specialising in Nepal's stock market (NEPSE). "
    "For casual conversation and greetings, respond naturally and warmly in 2-4 sentences. "
    "Briefly mention you can help with NEPSE stock prices, news, technical indicators, and sector analysis. "
    "If the user's question touches on investment advice (e.g., 'should I buy?'), "
    "always end with: DISCLAIMER: This is for educational purposes only. Not financial advice."
)

# ── Provider Configuration ────────────────────────────────────
PROVIDERS = [
    {
        "name": "groq",
        "base_url": "https://api.groq.com/openai/v1/chat/completions",
        "api_key_env": "GROQ_API_KEY",
        "model": "llama-3.1-8b-instant",
        "priority": 1,
        "daily_token_limit": 500_000,
        "auth_style": "bearer",       # Authorization: Bearer <key>
    },
    {
        "name": "google_ai_studio",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "api_key_env": "GOOGLE_AI_API_KEY",
        "model": "gemini-2.5-flash",
        "priority": 2,
        "daily_token_limit": 1_500_000,
        "auth_style": "query_param",   # ?key=<key> appended to URL
    },
    {
        "name": "openrouter",
        "base_url": "https://openrouter.ai/api/v1/chat/completions",
        "api_key_env": "OPENROUTER_API_KEY",
        "model": "meta-llama/llama-3.2-3b-instruct:free",
        "priority": 3,
        "daily_token_limit": 50_000,
        "auth_style": "bearer",
    },
    {
        "name": "ollama",
        "base_url": "http://localhost:11434/v1/chat/completions",
        "api_key_env": None,           # No key needed
        "model": "llama3.2:3b",
        "priority": 4,
        "daily_token_limit": 999_999_999,
        "auth_style": "none",
    },
]


# ── call_llm ──────────────────────────────────────────────────

async def call_llm(prompt_or_messages: str | list[dict], max_tokens: int = 800) -> tuple[str, str]:
    """
    Calls LLM using the fallback chain.

    Tries providers in priority order. Skips exhausted providers.

    Returns:
        (answer_text, provider_name_used, tokens_used)

    Raises:
        RuntimeError: If ALL providers fail (caller should return 503).
    """
    errors = []

    for provider in PROVIDERS:
        name = provider["name"]

        # Skip if no API key configured (except Ollama)
        api_key = None
        if provider["api_key_env"]:
            api_key = config(provider["api_key_env"], default="")
            if not api_key:
                errors.append(f"{name}: no API key configured")
                continue

        # Skip if provider marked exhausted
        if is_llm_provider_exhausted(name):
            errors.append(f"{name}: marked exhausted (rate-limited)")
            continue

        try:
            answer, tokens_used = await _call_provider(
                provider, api_key, prompt_or_messages, max_tokens
            )
            return answer, name, tokens_used

        except _ProviderRateLimited as e:
            mark_llm_provider_exhausted(name, ttl=3600)
            errors.append(f"{name}: rate limited (429) — {e}")
            logger.warning(
                "LLM provider %s rate limited (429), skipping for 1h",
                name,
                extra={"event": "llm_rate_limited", "provider": name},
            )

        except _ProviderAuthError as e:
            mark_llm_provider_exhausted(name, ttl=86400)
            errors.append(f"{name}: auth error (401/403) — {e}")
            logger.warning(
                "LLM provider %s auth error, skipping for 24h",
                name,
                extra={"event": "llm_auth_error", "provider": name},
            )

        except Exception as e:
            errors.append(f"{name}: {type(e).__name__}: {e}")
            logger.warning(
                "LLM provider %s failed: %s",
                name, e,
                extra={"event": "llm_provider_error", "provider": name},
            )

    # All providers failed
    error_summary = "; ".join(errors)
    logger.error(
        "All LLM providers failed: %s", error_summary,
        extra={"event": "llm_chain_exhausted"},
    )
    raise RuntimeError(f"All LLM providers failed: {error_summary}")


# ── Internal helpers ──────────────────────────────────────────

class _ProviderRateLimited(Exception):
    """HTTP 429 from LLM provider."""

class _ProviderAuthError(Exception):
    """HTTP 401 or 403 from LLM provider."""


async def _call_provider(
    provider: dict,
    api_key: str | None,
    prompt_or_messages: str | list[dict],
    max_tokens: int,
) -> tuple[str, int]:
    """
    Makes a single OpenAI-compatible chat completion request.

    Returns:
        (answer_text, tokens_used)

    Raises:
        _ProviderRateLimited on 429
        _ProviderAuthError on 401/403
        Exception on any other error
    """
    name = provider["name"]
    url = provider["base_url"]
    model = provider["model"]
    auth_style = provider["auth_style"]

    # Build headers
    headers = {"Content-Type": "application/json"}
    if auth_style == "bearer" and api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    elif auth_style == "query_param" and api_key:
        # Google AI Studio: append key as query parameter
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}key={api_key}"

    # Build request body (OpenAI-compatible format)
    if isinstance(prompt_or_messages, list):
        messages_payload = [
            {"role": "system", "content": SYSTEM_PROMPT},
        ] + prompt_or_messages
    else:
        messages_payload = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt_or_messages},
        ]

    body = {
        "model": model,
        "messages": messages_payload,
        "max_tokens": max_tokens,
        "temperature": 0.7,
    }

    start = time.time()

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=body, headers=headers)

    latency_ms = int((time.time() - start) * 1000)

    # Handle error status codes
    if resp.status_code == 429:
        raise _ProviderRateLimited(resp.text[:200])
    if resp.status_code in (401, 403):
        raise _ProviderAuthError(resp.text[:200])
    resp.raise_for_status()

    # Parse response
    data = resp.json()
    choices = data.get("choices", [])
    if not choices:
        raise ValueError(f"No choices in response from {name}")

    answer = choices[0].get("message", {}).get("content", "").strip()

    # Estimate tokens used
    usage = data.get("usage", {})
    tokens_used = usage.get("total_tokens", 0)
    if not tokens_used:
        # Fallback estimation: words / 0.75
        tokens_used = int(len(prompt.split()) / 0.75) + int(
            len(answer.split()) / 0.75
        )

    # Track usage
    track_llm_tokens(name, tokens_used)

    logger.info(
        "LLM call to %s: %d tokens, %dms, model=%s",
        name, tokens_used, latency_ms, model,
        extra={
            "event": "llm_call",
            "provider": name,
            "model": model,
            "tokens_used": tokens_used,
            "latency_ms": latency_ms,
        },
    )

    return answer, tokens_used


# ── build_rag_prompt ──────────────────────────────────────────

def build_rag_prompt(
    question: str,
    tool_outputs: list[str],
    max_input_tokens: int = 3000,
    route: str = None,
) -> str:
    """
    Assembles the final RAG prompt from tool outputs.

    Enforces a 3,000 token budget (4,500 for news-heavy routes). If over budget,
    truncates the longest tool output by 20% iteratively. Never truncates the question.

    Args:
        question: User's original question.
        tool_outputs: List of plain-text tool output strings.
        max_input_tokens: Max token budget for the prompt.
        route: Query classification route.

    Returns:
        Assembled prompt string ready for call_llm().
    """
    if route in ('full_agent', 'compare'):
        max_input_tokens = max(max_input_tokens, 4500)

    # Filter out empty outputs
    outputs = [o for o in tool_outputs if o and o.strip()]

    if not outputs:
        # No context — still ask the question
        return (
            f"QUESTION: {question}\n\n"
            "No live data was retrieved for this query. "
            "Do NOT invent prices, RSI values, or indicator numbers. "
            "Tell the user to check merolagani.com or sharesansar.com "
            "for current data. You may explain concepts generally.\n"
        )

    # Build context block
    def _build_prompt(parts: list[str]) -> str:
        xml_parts = []
        for part in parts:
            part_str = part.strip()
            import re
            sym_match = re.search(r"\b([A-Z]{2,6})\b", part_str)
            sym_attr = f" symbol=\"{sym_match.group(1)}\"" if sym_match else ""

            if "SQL DATA:" in part_str or "Indicators:" in part_str:
                xml_parts.append(f"<sql_data{sym_attr}>\n{part_str}\n</sql_data>")
            elif "Graph Context:" in part_str:
                xml_parts.append(f"<graph_data{sym_attr}>\n{part_str}\n</graph_data>")
            elif "Recent news for" in part_str:
                xml_parts.append(f"<news_data{sym_attr}>\n{part_str}\n</news_data>")
            elif "From " in part_str:
                xml_parts.append(f"<vector_data>\n{part_str}\n</vector_data>")
            else:
                xml_parts.append(f"<additional_context>\n{part_str}\n</additional_context>")
                
        context = "\n".join(xml_parts)
        return (
            f"<context>\n{context}\n</context>\n\n"
            f"QUESTION: {question}\n\n"
            "INSTRUCTIONS: Using ONLY the context above, answer concisely.\n"
            "- You MUST write your step-by-step thinking process inside a `<thinking>` block before the final answer.\n"
            "- The UI already displays a PriceCard, SignalsTable, and a News Section with the actual headlines.\n"
            "- Do NOT list LTP, Volume, Range, RSI, MACD, EMA, BB values as bullet points.\n"
            "- Do NOT list news headlines as bullet points.\n"
            "- Instead, provide a 2-3 sentence SYNTHESIS combining price action, indicator momentum, and news sentiment.\n"
            "- NEVER include a 'Compare' or 'Comparison' section unless multiple stocks were queried.\n"
            "- NEVER explain what indicators mean or how they work.\n"
            "- NEVER write '[context unclear]' or similar placeholders.\n"
            "- Begin your response with: <thinking>\n"
        )

    def _estimate_tokens(text: str) -> int:
        """Estimate token count: words / 0.75."""
        return max(1, int(len(text.split()) / 0.75))

    # Iteratively truncate if over budget
    working_outputs = list(outputs)
    prompt = _build_prompt(working_outputs)
    iterations = 0
    max_iterations = 10  # safety guard

    while _estimate_tokens(prompt) > max_input_tokens and iterations < max_iterations:
        # Find the longest output
        longest_idx = max(range(len(working_outputs)),
                         key=lambda i: len(working_outputs[i]))
        current = working_outputs[longest_idx]

        # Truncate by 20%
        new_len = int(len(current) * 0.8)
        if new_len < 50:
            # Too short — remove entirely
            working_outputs.pop(longest_idx)
            if not working_outputs:
                break
        else:
            working_outputs[longest_idx] = current[:new_len] + "..."

        prompt = _build_prompt(working_outputs)
        iterations += 1

    if iterations > 0:
        logger.warning(
            "RAG prompt truncated after %d iterations (budget: %d tokens)",
            iterations, max_input_tokens,
            extra={
                "event": "prompt_truncation",
                "iterations": iterations,
                "max_tokens": max_input_tokens,
            },
        )

    return prompt


# ── stream_llm ────────────────────────────────────────────────

async def stream_llm(
    prompt_or_messages: str | list[dict], max_tokens: int = 800
) -> AsyncGenerator[str | tuple, None]:
    """
    Streaming LLM call with fallback chain.

    Tries providers in priority order. For each provider, sends
    stream=True to the OpenAI-compatible chat completions endpoint,
    then parses SSE data lines and yields individual tokens.

    Yields:
        str: Individual content tokens as they arrive.
        tuple: ("__meta__", provider_name, tokens_used) as the final yield,
               so the caller knows which provider was used and how many tokens.

    If ALL streaming attempts fail, falls back to non-streaming
    call_llm() and yields the entire response at once.
    """
    errors = []

    for provider in PROVIDERS:
        name = provider["name"]

        # Skip if no API key configured (except Ollama)
        api_key = None
        if provider["api_key_env"]:
            api_key = config(provider["api_key_env"], default="")
            if not api_key:
                errors.append(f"{name}: no API key")
                continue

        # Skip if provider marked exhausted
        if is_llm_provider_exhausted(name):
            errors.append(f"{name}: exhausted")
            continue

        try:
            token_count = 0
            async for token in _stream_provider(
                provider, api_key, prompt_or_messages, max_tokens
            ):
                token_count += 1
                yield token

            # Track approximate token usage
            if isinstance(prompt_or_messages, list):
                prompt_text = " ".join([m.get("content", "") for m in prompt_or_messages])
            else:
                prompt_text = prompt_or_messages
            prompt_tokens = int(len(prompt_text.split()) / 0.75)
            track_llm_tokens(name, prompt_tokens + token_count)

            logger.info(
                "stream_llm via %s: ~%d tokens streamed",
                name, token_count,
                extra={
                    "event": "stream_llm",
                    "provider": name,
                    "tokens_streamed": token_count,
                },
            )
            # Yield metadata as final item
            yield ("__meta__", name, prompt_tokens + token_count)
            return

        except _ProviderRateLimited as e:
            mark_llm_provider_exhausted(name, ttl=3600)
            errors.append(f"{name}: 429")
            logger.warning(
                "stream_llm %s rate limited", name,
                extra={"event": "stream_rate_limited", "provider": name},
            )

        except _ProviderAuthError as e:
            mark_llm_provider_exhausted(name, ttl=86400)
            errors.append(f"{name}: auth error")
            logger.warning(
                "stream_llm %s auth error", name,
                extra={"event": "stream_auth_error", "provider": name},
            )

        except Exception as e:
            errors.append(f"{name}: {e}")
            logger.warning(
                "stream_llm %s failed: %s", name, e,
                extra={"event": "stream_provider_error", "provider": name},
            )

    # All streaming attempts failed — fall back to non-streaming
    logger.warning(
        "All stream providers failed (%s), falling back to call_llm",
        "; ".join(errors),
        extra={"event": "stream_fallback"},
    )
    try:
        answer, provider_name, tokens_used = await call_llm(prompt, max_tokens)
        yield answer
        yield ("__meta__", provider_name, tokens_used)
    except RuntimeError:
        yield (
            "I'm sorry, all LLM providers are temporarily unavailable. "
            "Please try again later.\n\n"
            "DISCLAIMER: This is for educational purposes only. "
            "Not financial advice."
        )
        yield ("__meta__", "none", 0)


async def stream_llm_chat(
    question: str,
) -> AsyncGenerator[str | tuple, None]:
    """
    Lightweight streaming LLM call for casual conversation.
    Uses CHAT_SYSTEM_PROMPT (friendly, no closed-book restriction).
    Max 200 tokens — keeps responses concise.
    """
    prompt = f"User: {question}\nAssistant:"
    async for token in _stream_with_system(CHAT_SYSTEM_PROMPT, prompt, max_tokens=200):
        yield token


async def _stream_with_system(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 400,
) -> AsyncGenerator[str | tuple, None]:
    """
    Internal helper: streams from provider chain using a custom system_prompt.
    Yields str tokens then a final ("__meta__", provider, tokens) tuple.
    """
    errors = []
    for provider in PROVIDERS:
        name = provider["name"]
        api_key = None
        if provider["api_key_env"]:
            api_key = config(provider["api_key_env"], default="")
            if not api_key:
                errors.append(f"{name}: no API key")
                continue
        if is_llm_provider_exhausted(name):
            errors.append(f"{name}: exhausted")
            continue
        try:
            name_ = provider["name"]
            url = provider["base_url"]
            model = provider["model"]
            auth_style = provider["auth_style"]
            headers = {"Content-Type": "application/json"}
            if auth_style == "bearer" and api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            elif auth_style == "query_param" and api_key:
                sep = "&" if "?" in url else "?"
                url = f"{url}{sep}key={api_key}"
            body = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": max_tokens,
                "temperature": 0.75,
                "stream": True,
            }
            token_count = 0
            async with httpx.AsyncClient(timeout=30.0) as client:
                async with client.stream("POST", url, json=body, headers=headers) as resp:
                    if resp.status_code == 429:
                        await resp.aread()
                        mark_llm_provider_exhausted(name_, ttl=3600)
                        errors.append(f"{name_}: 429")
                        continue
                    if resp.status_code in (401, 403):
                        await resp.aread()
                        mark_llm_provider_exhausted(name_, ttl=86400)
                        errors.append(f"{name_}: auth error")
                        continue
                    if resp.status_code >= 400:
                        await resp.aread()
                        errors.append(f"{name_}: HTTP {resp.status_code}")
                        continue
                    import json as _json
                    async for line in resp.aiter_lines():
                        line = line.strip()
                        if not line or not line.startswith("data:"):
                            continue
                        data_str = line[5:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = _json.loads(data_str)
                            content = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                            if content:
                                token_count += 1
                                yield content
                        except Exception:
                            continue
            prompt_tokens = int(len(user_prompt.split()) / 0.75)
            track_llm_tokens(name_, prompt_tokens + token_count)
            yield ("__meta__", name_, prompt_tokens + token_count)
            return
        except Exception as e:
            errors.append(f"{name}: {e}")
            logger.warning("_stream_with_system %s failed: %s", name, e)

    # Fallback: non-streaming
    try:
        import httpx as _httpx
        for provider in PROVIDERS:
            name = provider["name"]
            api_key = None
            if provider["api_key_env"]:
                api_key = config(provider["api_key_env"], default="")
                if not api_key:
                    continue
            if is_llm_provider_exhausted(name):
                continue
            url = provider["base_url"]
            model = provider["model"]
            auth_style = provider["auth_style"]
            headers = {"Content-Type": "application/json"}
            if auth_style == "bearer" and api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            elif auth_style == "query_param" and api_key:
                sep = "&" if "?" in url else "?"
                url = f"{url}{sep}key={api_key}"
            body = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": max_tokens,
                "temperature": 0.75,
            }
            async with _httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, json=body, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                answer = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                tokens = data.get("usage", {}).get("total_tokens", 0)
                track_llm_tokens(name, tokens)
                yield answer
                yield ("__meta__", name, tokens)
                return
    except Exception:
        pass
    yield "I'm sorry, I'm temporarily unavailable. Please try again later."
    yield ("__meta__", "none", 0)


async def _stream_provider(
    provider: dict,
    api_key: str | None,
    prompt_or_messages: str | list[dict],
    max_tokens: int,
) -> AsyncGenerator[str, None]:
    """
    Streams tokens from a single OpenAI-compatible provider.

    Sends stream=True, reads the response line by line,
    parses SSE 'data: {...}' lines, and yields delta.content tokens.

    Raises:
        _ProviderRateLimited on 429
        _ProviderAuthError on 401/403
        Exception on any other error
    """
    name = provider["name"]
    url = provider["base_url"]
    model = provider["model"]
    auth_style = provider["auth_style"]

    # Build headers
    headers = {"Content-Type": "application/json"}
    if auth_style == "bearer" and api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    elif auth_style == "query_param" and api_key:
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}key={api_key}"

    # Build request body with stream=True
    if isinstance(prompt_or_messages, list):
        messages_payload = [
            {"role": "system", "content": SYSTEM_PROMPT},
        ] + prompt_or_messages
    else:
        messages_payload = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt_or_messages},
        ]

    body = {
        "model": model,
        "messages": messages_payload,
        "max_tokens": max_tokens,
        "temperature": 0.7,
        "stream": True,
    }

    start = time.time()

    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream(
            "POST", url, json=body, headers=headers
        ) as resp:
            # Handle error status codes before reading body
            if resp.status_code == 429:
                await resp.aread()
                raise _ProviderRateLimited(f"{name} returned 429")
            if resp.status_code in (401, 403):
                await resp.aread()
                raise _ProviderAuthError(f"{name} returned {resp.status_code}")
            if resp.status_code >= 400:
                await resp.aread()
                raise Exception(
                    f"{name} returned HTTP {resp.status_code}: "
                    f"{resp.text[:200]}"
                )

            # Parse SSE lines
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line:
                    continue
                if not line.startswith("data:"):
                    continue

                data_str = line[5:].strip()

                # End of stream marker
                if data_str == "[DONE]":
                    break

                try:
                    import json
                    chunk = json.loads(data_str)
                    choices = chunk.get("choices", [])
                    if choices:
                        delta = choices[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content
                except (json.JSONDecodeError, KeyError, IndexError):
                    # Skip malformed chunks
                    continue

    latency_ms = int((time.time() - start) * 1000)
    logger.info(
        "Streamed from %s in %dms", name, latency_ms,
        extra={
            "event": "stream_complete",
            "provider": name,
            "latency_ms": latency_ms,
        },
    )
