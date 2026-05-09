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
    "## MANDATORY Rules (violating ANY of these is UNACCEPTABLE):\n"
    "1. Each 'SQL DATA:' block in the context IS the stock's current price. "
    "State the close value as the latest price. "
    "NEVER say 'no price data' or 'limited information' if SQL DATA exists for that symbol.\n"
    "2. If there are SQL DATA blocks for MULTIPLE symbols (e.g., NABIL and NICA), "
    "you MUST present price data for ALL of them. Skipping ANY symbol's data is WRONG.\n"
    "3. DO NOT explain what indicators mean. No definitions. No theory. "
    "Wrong: 'RSI is a momentum indicator that measures...' "
    "Right: 'RSI: 51.0 — neutral' "
    "Only explain if user says 'what is RSI' or 'explain MACD'.\n"
    "4. NEVER invent prices, indicators, news, or URLs not in context.\n"
    "5. For news: if only a headline exists with no summary, just show the headline "
    "and source. NEVER write '[context unclear]', '[no context]', or similar placeholders.\n"
    "6. The UI already shows a PriceCard with LTP/Volume/Range and a SignalsTable "
    "with RSI/MACD/EMA/BB. Do NOT repeat these exact numbers in your text. "
    "Instead, provide a brief 1-2 sentence ANALYSIS or commentary on what the data means "
    "for the stock (e.g., 'NABIL is trading near its 52-week high with neutral momentum').\n\n"
    "## Format:\n"
    "Your response should be a brief, professional synthesis of the stock's status.\n"
    "- **Price & Trend**: Provide a 1-2 sentence analysis combining price action and indicator momentum.\n"
    "- **News**: If news exists, summarize the overall sentiment in 1 sentence. DO NOT list individual news articles (the UI shows them).\n"
    "- **Comparison**: ONLY if there are multiple stocks in the context, provide a brief comparison of their performance.\n\n"
    "Always end with: \n\nDISCLAIMER: This is for educational purposes only. Not financial advice."
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

async def call_llm(prompt: str, max_tokens: int = 800) -> tuple[str, str]:
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
                provider, api_key, prompt, max_tokens
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
    prompt: str,
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
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
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
) -> str:
    """
    Assembles the final RAG prompt from tool outputs.

    Enforces a 3,000 token budget. If over budget, truncates the
    longest tool output by 20% iteratively. Never truncates the question.

    Args:
        question: User's original question.
        tool_outputs: List of plain-text tool output strings.
        max_input_tokens: Max token budget for the prompt.

    Returns:
        Assembled prompt string ready for call_llm().
    """
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
        context = "\n---\n".join(parts)
        return (
            f"=== CONTEXT ===\n{context}\n=== END CONTEXT ===\n\n"
            f"QUESTION: {question}\n\n"
            "INSTRUCTIONS: Using ONLY the context above, answer concisely.\n"
            "- The UI already displays a PriceCard, SignalsTable, and a News Section with the actual headlines.\n"
            "- Do NOT list LTP, Volume, Range, RSI, MACD, EMA, BB values as bullet points.\n"
            "- Do NOT list news headlines as bullet points.\n"
            "- Instead, provide a 2-3 sentence SYNTHESIS combining price action, indicator momentum, and news sentiment.\n"
            "- NEVER include a 'Compare' or 'Comparison' section unless multiple stocks were queried.\n"
            "- NEVER explain what indicators mean or how they work.\n"
            "- NEVER write '[context unclear]' or similar placeholders.\n"
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
    prompt: str, max_tokens: int = 800
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
                provider, api_key, prompt, max_tokens
            ):
                token_count += 1
                yield token

            # Track approximate token usage
            prompt_tokens = int(len(prompt.split()) / 0.75)
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


async def _stream_provider(
    provider: dict,
    api_key: str | None,
    prompt: str,
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
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
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
