"""
LLM Client with 4-provider fallback chain.

Provider priority:
    1. Groq        — llama-3.1-8b-instant   (fastest, free 500K tokens/day)
    2. Google AI   — gemini-2.5-flash        (best quality, free 1.5M/day)
    3. OpenRouter  — llama-3.2-3b:free       (fallback, 50K/day)

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
    "You are NEPSE AI, a sharp and grounded Nepal Stock Exchange analyst. "
    "You speak directly and plainly, like a senior analyst briefing a colleague — "
    "not like a robot reading a spreadsheet.\n\n"

    "## VOICE & PERSONALITY (READ THIS FIRST):\n"
    "1. Write in flowing prose like a financial analyst talking to a client. "
    "Never use bullet points, numbered lists, or section headers.\n"
    "2. Lead with the most interesting or actionable insight — not a data dump of numbers.\n"
    "3. Weave price action, indicators, and news together into a single narrative paragraph.\n"
    "4. Interpret what indicators MEAN, don't just report them.\n"
    "   WRONG: 'RSI: 46.2 (Neutral). MACD: -3.75 (Bearish). BB Position: 30%.'\n"
    "   RIGHT: 'NICA is drifting lower under quiet selling pressure — the MACD has tipped "
    "negative and the price keeps hugging the lower Bollinger Band without bouncing, though "
    "RSI at 46 still has room before hitting oversold territory.'\n"
    "5. For news queries: explain what the news MEANS for the stock, don't just describe events.\n"
    "   WRONG: 'NIC Asia Bank partnered with Annapurna Group.'\n"
    "   RIGHT: 'NICA's tie-up with Annapurna Group signals the bank is pushing retail "
    "engagement as a growth lever while lending margins stay compressed.'\n"
    "6. If indicators conflict (e.g. RSI neutral but MACD bearish), acknowledge the tension "
    "explicitly: 'The setup is mixed — momentum is leaking out on the MACD side, but RSI "
    "hasn't confirmed a breakdown yet.'\n"
    "7. End with ONE specific, actionable observation. Not a generic disclaimer line.\n"
    "8. Keep it under 5 sentences for simple queries. One paragraph per stock for comparisons.\n"
    "9. Never use filler phrases like 'Great question!' or 'Certainly!' or 'It seems like'.\n"
    "10. Do NOT repeat numbers already shown in the price card above your text "
    "(LTP, Volume, Day Range, 52W Range, VWAP are already displayed).\n"
    "11. Do NOT explain what indicators mean or how they work.\n"
    "12. Never use headers like 'Price & Trend:' or 'News:' — just write naturally.\n\n"

    "## IDENTITY RULES:\n"
    "- You only discuss NEPSE-listed stocks. If asked about Indian, US, or other markets, "
    "politely decline.\n"
    "- If a symbol is not in the context, say: 'I don't have data for [SYMBOL] right now — "
    "try querying it directly or check if the ticker is correct.'\n"
    "- Always end every response with: "
    "'DISCLAIMER: This is for educational purposes only. Not financial advice.'\n\n"

    "## DATA GROUNDING RULES:\n"
    "1. CLOSED-BOOK mode: you have NO knowledge beyond what is in the <context> block.\n"
    "2. If a number, price, date, or percentage is NOT in the <context> block, "
    "say 'Data not available.' — never guess.\n"
    "3. For news: ONLY summarize content that appears in <news_data>. "
    "If <news_data> is empty or says NO_NEWS_FOUND, say 'No recent news found for [SYMBOL]' "
    "and do NOT invent or recall any news from training data.\n"
    "4. Each 'SQL DATA:' block IS the stock's current price. State the close value as the "
    "latest price. NEVER say 'no price data' if SQL DATA exists.\n"
    "5. If SQL DATA blocks exist for MULTIPLE symbols, you MUST analyze ALL of them. "
    "Skipping any symbol is wrong.\n"
    "6. NEVER extrapolate or calculate values not explicitly given.\n"
    "7. NEVER state specific financial ratios (NPL%, NPM%, ROE%, CAR%) for a named company "
    "unless that exact figure appears in the <context> block with its source. "
    "Fabricating financial metrics is worse than saying 'data not available.'\n"
    "8. FORBIDDEN FABRICATIONS — Do not generate ANY of these unless they appear in <context>:\n"
    "   NPL ratio, Net Profit Margin, ROE, ROA, CAR, Cost of Funds, CD ratio, "
    "   P/E ratio, P/B ratio, Book Value, EPS (specific number), Dividend Yield, "
    "   operating profit, net interest income, provisions, loan loss ratio.\n"
    "   If the user asks for any of these, respond: "
    "   'That specific ratio is not in my current data. Check the company's latest "
    "   quarterly report on sharesansar.com or merolagani.com for audited figures.'\n\n"

    "## INDICATOR CONSISTENCY RULES:\n"
    "1. RSI < 40: use bearish language. Never suggest buying.\n"
    "2. RSI 40–55: 'neutral momentum'. Do not lean bullish or bearish without another signal.\n"
    "3. RSI > 60: neutral-to-bullish language is allowed.\n"
    "4. MACD negative: acknowledge bearish momentum. Do not suggest buying unless "
    "RSI > 55 AND price is above EMA.\n"
    "5. MACD positive: acknowledge bullish momentum.\n"
    "6. Conflicting indicators: always say 'mixed signals' and explain. Never pick one side.\n"
    "7. NEVER give a buy or sell conclusion without citing which 2+ indicators support it.\n\n"

    "## COMPARISON RULES:\n"
    "1. Discuss ALL mentioned symbols — never drop one.\n"
    "2. Rank them explicitly at the end: "
    "'Based on current indicators: 1. NABIL (RSI 62, bullish MACD) 2. NICA (RSI 46, bearish MACD)'\n"
    "3. Resolve pronouns like 'it/they/those/which one' from <conversation_history>. "
    "Never ask the user to repeat themselves.\n\n"

    "## CONVERSATION MEMORY RULES:\n"
    "1. Read <conversation_history> carefully before answering.\n"
    "2. For follow-up questions, use stocks and data from previous turns.\n"
    "3. Do NOT repeat prices, indicators, or news summaries already stated in the last "
    "assistant message.\n\n"

    "## THINKING (INTERNAL ONLY):\n"
    "Before writing your answer, briefly think through: which indicators are present, "
    "what the news implies, and what the single most important insight is. "
    "Do NOT output this thinking — go straight to your prose answer.\n\n"

    "## CORRECT BEHAVIOR EXAMPLE:\n"
    "User: 'Should I buy [STOCK]?'\n"
    "Context: RSI=46, MACD=-3.75, BB Position=30%, no bullish news\n"
    "WRONG: 'It seems like a good time to buy [STOCK] based on the neutral RSI.'\n"
    "CORRECT: Explain that the setup is mixed using the specific numbers from context. "
    "Cite which indicators are bearish, which are neutral, and what would need to "
    "change before the setup improves. Never copy this example verbatim — adapt to "
    "the actual data.\n"
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
        "auth_style": "bearer",
    },
    {
        "name": "google_ai_studio",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "api_key_env": "GOOGLE_AI_API_KEY",
        "model": "gemini-2.5-flash",
        "priority": 2,
        "daily_token_limit": 1_500_000,
        "auth_style": "bearer",
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
        "api_key_env": None,
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
    Returns: (answer_text, provider_name_used, tokens_used)
    Raises: RuntimeError if ALL providers fail.
    """
    errors = []

    for provider in PROVIDERS:
        name = provider["name"]

        api_key = None
        if provider["api_key_env"]:
            api_key = config(provider["api_key_env"], default="")
            if not api_key:
                errors.append(f"{name}: no API key configured")
                continue

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
            logger.warning("LLM provider %s rate limited (429), skipping for 1h", name)

        except _ProviderAuthError as e:
            mark_llm_provider_exhausted(name, ttl=86400)
            errors.append(f"{name}: auth error (401/403) — {e}")
            logger.warning("LLM provider %s auth error, skipping for 24h", name)

        except Exception as e:
            errors.append(f"{name}: {type(e).__name__}: {e}")
            logger.warning("LLM provider %s failed: %s", name, e)

    error_summary = "; ".join(errors)
    logger.error("All LLM providers failed: %s", error_summary)
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
    Returns: (answer_text, tokens_used)
    """
    name = provider["name"]
    url = provider["base_url"]
    model = provider["model"]
    auth_style = provider["auth_style"]

    headers = {"Content-Type": "application/json"}
    if auth_style == "bearer" and api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    elif auth_style == "query_param" and api_key:
        # Google AI Studio uses ?key= param ONLY — no Bearer header
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}key={api_key}"

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

    if resp.status_code == 429:
        raise _ProviderRateLimited(resp.text[:200])
    if resp.status_code in (401, 403):
        raise _ProviderAuthError(resp.text[:200])
    resp.raise_for_status()

    data = resp.json()
    choices = data.get("choices", [])
    if not choices:
        raise ValueError(f"No choices in response from {name}")

    answer = choices[0].get("message", {}).get("content", "").strip()

    usage = data.get("usage", {})
    tokens_used = usage.get("total_tokens", 0)
    if not tokens_used:
        prompt_text = " ".join(m.get("content", "") for m in messages_payload)
        tokens_used = int(len(prompt_text.split()) / 0.75) + int(
            len(answer.split()) / 0.75
        )

    track_llm_tokens(name, tokens_used)

    logger.info(
        "LLM call to %s: %d tokens, %dms, model=%s",
        name, tokens_used, latency_ms, model,
    )

    return answer, tokens_used


# ── build_rag_prompt ──────────────────────────────────────────

def build_rag_prompt(
    question: str,
    tool_outputs: list[str],
    max_input_tokens: int = 3000,
    route: str = None,
    history: list[dict] = None,
) -> str:
    """
    Assembles the final RAG prompt from tool outputs.

    Enforces a token budget. If over budget, truncates the longest
    tool output by 20% iteratively. Never truncates the question.
    """
    if route in ('full_agent', 'compare'):
        max_input_tokens = max(max_input_tokens, 4500)

    outputs = [o for o in tool_outputs if o and o.strip()]

    # Build conversation history block
    history_block = ""
    if history and route != 'screener':
        history_block = "<conversation_history>\n"
        for turn in history[-6:]:
            role = turn.get("role", "user")
            # Smart truncation: assistant messages are verbose, user messages are short
            content = turn.get("content", "")
            if role == "assistant":
                content = content[:600]
            else:
                content = content[:400]
            history_block += f"<{role}>{content}</{role}>\n"
        history_block += "</conversation_history>\n\n"

    if not outputs:
        return (
            f"{history_block}"
            f"QUESTION: {question}\n\n"
            "No live data was retrieved for this query. "
            "Do NOT invent prices, RSI values, or indicator numbers. "
            "Tell the user to check merolagani.com or sharesansar.com "
            "for current data. You may explain concepts generally.\n"
        )

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
            elif "NO_NEWS_FOUND" in part_str:
                xml_parts.append(f"<news_data{sym_attr}>\nNO_NEWS_FOUND. Do not mention any news sources. Do not invent headlines.\n</news_data>")
            elif "From " in part_str:
                xml_parts.append(f"<vector_data>\n{part_str}\n</vector_data>")
            else:
                xml_parts.append(f"<additional_context>\n{part_str}\n</additional_context>")

        context = "\n".join(xml_parts)
        return (
            f"{history_block}"
            f"<context>\n{context}\n</context>\n\n"
            f"QUESTION: {question}\n\n"
            "INSTRUCTIONS:\n"
            "- Answer using ONLY the context above and conversation_history for follow-ups.\n"
            "- Write in flowing prose like a senior analyst — NO bullet points, NO headers, NO numbered lists.\n"
            "- Lead with the single most interesting insight, not a price recap.\n"
            "- Weave indicators and news into ONE narrative paragraph per stock.\n"
            "- The UI already shows price cards and news headlines — do NOT repeat raw numbers or list headlines.\n"
            "- If <news_data> is empty or says NO_NEWS_FOUND: say 'No recent news found for [SYMBOL].' Do NOT invent news.\n"
            "- If a symbol appears in the question but has no context data, say so directly.\n"
            "- End with: DISCLAIMER: This is for educational purposes only. Not financial advice.\n"
        )

    def _estimate_tokens(text: str) -> int:
        return max(1, int(len(text.split()) / 0.75))

    working_outputs = list(outputs)
    prompt = _build_prompt(working_outputs)
    iterations = 0
    max_iterations = 10

    while _estimate_tokens(prompt) > max_input_tokens and iterations < max_iterations:
        longest_idx = max(range(len(working_outputs)),
                         key=lambda i: len(working_outputs[i]))
        current = working_outputs[longest_idx]
        new_len = int(len(current) * 0.8)
        if new_len < 50:
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
        )

    return prompt


# ── stream_llm ────────────────────────────────────────────────

async def stream_llm(
    prompt_or_messages: str | list[dict], max_tokens: int = 800
) -> AsyncGenerator[str | tuple, None]:
    """
    Streaming LLM call with fallback chain.

    Yields str tokens as they arrive, then a final
    ("__meta__", provider_name, tokens_used) tuple.

    Falls back to non-streaming call_llm() if all streaming attempts fail.
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
            token_count = 0
            async for token in _stream_provider(
                provider, api_key, prompt_or_messages, max_tokens
            ):
                token_count += 1
                yield token

            if isinstance(prompt_or_messages, list):
                prompt_text = " ".join([m.get("content", "") for m in prompt_or_messages])
            else:
                prompt_text = prompt_or_messages
            prompt_tokens = int(len(prompt_text.split()) / 0.75)
            track_llm_tokens(name, prompt_tokens + token_count)

            logger.info("stream_llm via %s: ~%d tokens streamed", name, token_count)
            yield ("__meta__", name, prompt_tokens + token_count)
            return

        except _ProviderRateLimited:
            mark_llm_provider_exhausted(name, ttl=3600)
            errors.append(f"{name}: 429")
            logger.warning("stream_llm %s rate limited", name)

        except _ProviderAuthError:
            mark_llm_provider_exhausted(name, ttl=86400)
            errors.append(f"{name}: auth error")
            logger.warning("stream_llm %s auth error", name)

        except Exception as e:
            errors.append(f"{name}: {e}")
            logger.warning("stream_llm %s failed: %s", name, e)

    # All streaming attempts failed — fall back to non-streaming
    logger.warning(
        "All stream providers failed (%s), falling back to call_llm",
        "; ".join(errors),
    )
    try:
        answer, provider_name, tokens_used = await call_llm(prompt_or_messages, max_tokens)
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
    Uses CHAT_SYSTEM_PROMPT. Max 200 tokens.
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
                        mark_llm_provider_exhausted(name, ttl=3600)
                        errors.append(f"{name}: 429")
                        continue
                    if resp.status_code in (401, 403):
                        await resp.aread()
                        mark_llm_provider_exhausted(name, ttl=86400)
                        errors.append(f"{name}: auth error")
                        continue
                    if resp.status_code >= 400:
                        await resp.aread()
                        errors.append(f"{name}: HTTP {resp.status_code}")
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
            track_llm_tokens(name, prompt_tokens + token_count)
            yield ("__meta__", name, prompt_tokens + token_count)
            return
        except Exception as e:
            errors.append(f"{name}: {e}")
            logger.warning("_stream_with_system %s failed: %s", name, e)

    # Fallback: non-streaming
    try:
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
            async with httpx.AsyncClient(timeout=30.0) as client:
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
    Raises _ProviderRateLimited, _ProviderAuthError, or Exception on failure.
    """
    name = provider["name"]
    url = provider["base_url"]
    model = provider["model"]
    auth_style = provider["auth_style"]

    headers = {"Content-Type": "application/json"}
    if auth_style == "bearer" and api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    elif auth_style == "query_param" and api_key:
        # Google AI Studio: ?key= param ONLY, no Bearer header
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}key={api_key}"

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
        async with client.stream("POST", url, json=body, headers=headers) as resp:
            if resp.status_code == 429:
                await resp.aread()
                raise _ProviderRateLimited(f"{name} returned 429")
            if resp.status_code in (401, 403):
                await resp.aread()
                raise _ProviderAuthError(f"{name} returned {resp.status_code}")
            if resp.status_code >= 400:
                await resp.aread()
                raise Exception(f"{name} returned HTTP {resp.status_code}: {resp.text[:200]}")

            async for line in resp.aiter_lines():
                line = line.strip()
                if not line or not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
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
                    continue

    latency_ms = int((time.time() - start) * 1000)
    logger.info("Streamed from %s in %dms", name, latency_ms)