"""
Cache Service — wraps Django cache with project-specific TTLs.

Handles caching for: OHLCV data, indicators, LLM responses, news,
token tracking, and provider rate-limit state.
"""
import hashlib
import logging
from django.core.cache import cache

logger = logging.getLogger('nepse_rag')

# ── TTL Constants (seconds) ───────────────────────────────────
TTL_INDICATORS = 900       # 15 minutes
TTL_OHLCV = 900            # 15 minutes
TTL_NEWS = 3600            # 1 hour
TTL_LLM_RESPONSE = 3600   # 1 hour
TTL_SYMBOLS = 86400        # 24 hours
TTL_DAILY = 86400          # 24 hours (for token tracking)

# Daily token limits per provider
_DAILY_TOKEN_LIMITS = {
    'groq': 500_000,
    'google_ai': 1_500_000,
    'openrouter': 50_000,
    'ollama': 999_999_999,
}


# ── LLM Response Cache ────────────────────────────────────────

def get_llm_cache_key(question: str, symbol: str) -> str:
    """Generates deterministic cache key from question + symbol."""
    raw = f"{question.lower().strip()}:{symbol.upper().strip()}"
    return "llm:" + hashlib.md5(raw.encode()).hexdigest()


def get_cached_llm_response(question: str, symbol: str) -> dict | None:
    """Returns cached full response dict or None on miss."""
    key = get_llm_cache_key(question, symbol)
    result = cache.get(key)
    if result is not None:
        logger.debug(f"LLM cache HIT: {key}")
    return result


def cache_llm_response(question: str, symbol: str, response: dict):
    """Caches full response dict for 1 hour."""
    key = get_llm_cache_key(question, symbol)
    cache.set(key, response, TTL_LLM_RESPONSE)
    logger.debug(f"LLM cache SET: {key}")


# ── News Cache ─────────────────────────────────────────────────

def get_cached_news(symbol: str) -> list | None:
    """Returns cached news list or None."""
    key = f"news:{symbol.upper()}"
    return cache.get(key)


def cache_news(symbol: str, news: list):
    """Caches news results for 1 hour."""
    key = f"news:{symbol.upper()}"
    cache.set(key, news, TTL_NEWS)


# ── Indicators Cache ──────────────────────────────────────────

def get_cached_indicators(symbol: str) -> dict | None:
    """Returns cached indicators dict or None."""
    key = f"indicators:{symbol.upper()}"
    return cache.get(key)


def cache_indicators(symbol: str, data: dict):
    """Caches computed indicators for 15 minutes."""
    key = f"indicators:{symbol.upper()}"
    cache.set(key, data, TTL_INDICATORS)


# ── OHLCV Cache ───────────────────────────────────────────────

def get_cached_ohlcv(symbol: str) -> dict | None:
    """Returns cached latest OHLCV dict or None."""
    key = f"ohlcv_latest:{symbol.upper()}"
    return cache.get(key)


def cache_ohlcv(symbol: str, data: dict):
    """Caches latest OHLCV for 15 minutes."""
    key = f"ohlcv_latest:{symbol.upper()}"
    cache.set(key, data, TTL_OHLCV)


# ── History Cache ─────────────────────────────────────────────

def get_cached_history(symbol: str, days: int) -> list | None:
    """Returns cached history list or None."""
    key = f"history:{symbol.upper()}:{days}"
    return cache.get(key)


def cache_history(symbol: str, days: int, data: list):
    """Caches history for 15 minutes."""
    key = f"history:{symbol.upper()}:{days}"
    cache.set(key, data, TTL_OHLCV)


# ── Symbols Cache ─────────────────────────────────────────────

def get_cached_symbols() -> list | None:
    """Returns cached all-symbols list or None."""
    return cache.get("all_symbols")


def cache_symbols(data: list):
    """Caches symbol list for 24 hours."""
    cache.set("all_symbols", data, TTL_SYMBOLS)


# ── Symbol Verification Cache ─────────────────────────────────

def get_cached_symbol_exists(symbol: str) -> bool | None:
    """Returns cached symbol existence check or None."""
    key = f"symbol_exists:{symbol.upper()}"
    return cache.get(key)


def cache_symbol_exists(symbol: str, exists: bool):
    """Caches symbol existence for 1 hour."""
    key = f"symbol_exists:{symbol.upper()}"
    cache.set(key, exists, TTL_LLM_RESPONSE)


# ── LLM Token Tracking ───────────────────────────────────────

def track_llm_tokens(provider: str, tokens: int):
    """
    Accumulates daily token usage per LLM provider.
    Cache key: 'llm_tokens_today:{provider}', TTL 86400.
    Logs WARNING when usage exceeds 80% of daily limit.
    """
    key = f"llm_tokens_today:{provider}"
    current = cache.get(key, 0)
    new_total = current + tokens
    cache.set(key, new_total, TTL_DAILY)

    limit = _DAILY_TOKEN_LIMITS.get(provider, 999_999_999)
    if new_total > limit * 0.8:
        logger.warning(
            f"LLM token usage HIGH: {provider} = {new_total}/{limit} "
            f"({new_total / limit * 100:.0f}%)",
            extra={
                'event': 'token_usage_high',
                'provider': provider,
                'tokens_used': new_total,
                'limit': limit,
            }
        )


def get_provider_token_usage(provider: str) -> int:
    """Returns total tokens used today for a provider."""
    key = f"llm_tokens_today:{provider}"
    return cache.get(key, 0)


# ── Provider Rate-Limit State ─────────────────────────────────

def is_llm_provider_exhausted(provider: str) -> bool:
    """Returns True if provider marked rate-limited in cache."""
    key = f"llm_exhausted:{provider}"
    return cache.get(key, False)


def mark_llm_provider_exhausted(provider: str, ttl: int = 3600):
    """Marks provider as rate-limited for TTL seconds."""
    key = f"llm_exhausted:{provider}"
    cache.set(key, True, ttl)
    logger.warning(
        f"LLM provider marked exhausted: {provider} (TTL={ttl}s)",
        extra={'event': 'provider_exhausted', 'provider': provider}
    )


def is_search_provider_exhausted(provider: str) -> bool:
    """Returns True if search provider marked exhausted."""
    key = f"search_exhausted:{provider}"
    return cache.get(key, False)


def mark_search_provider_exhausted(provider: str, ttl: int = 3600):
    """Marks search provider as exhausted for TTL seconds."""
    key = f"search_exhausted:{provider}"
    cache.set(key, True, ttl)
    logger.warning(
        f"Search provider marked exhausted: {provider} (TTL={ttl}s)",
        extra={'event': 'search_exhausted', 'provider': provider}
    )
