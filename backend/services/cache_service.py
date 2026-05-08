import hashlib
from django.core.cache import cache

# TTL constants
TTL_INDICATORS = 900       # 15 minutes
TTL_OHLCV      = 900       # 15 minutes
TTL_NEWS       = 3600      # 1 hour
TTL_LLM        = 3600      # 1 hour
TTL_SYMBOLS    = 86400     # 24 hours

def get_llm_cache_key(question: str, symbol: str) -> str:
    """MD5 hash of normalized question + symbol."""
    raw = f"{question.lower().strip()}:{symbol.upper().strip()}"
    return "llm:" + hashlib.md5(raw.encode()).hexdigest()

def get_cached_llm_response(question: str, symbol: str) -> dict | None:
    """Returns cached full response dict or None on miss."""
    return cache.get(get_llm_cache_key(question, symbol))

def cache_llm_response(question: str, symbol: str,
                       response: dict, ttl: int = TTL_LLM):
    """Cache full response dict."""
    cache.set(get_llm_cache_key(question, symbol), response, timeout=ttl)

def get_cached_news(symbol: str) -> list | None:
    """Returns cached news list or None."""
    return cache.get(f"news:{symbol.upper()}")

def cache_news(symbol: str, news: list, ttl: int = TTL_NEWS):
    """Cache news results."""
    cache.set(f"news:{symbol.upper()}", news, timeout=ttl)

def get_cached_indicators(symbol: str) -> dict | None:
    """Returns cached indicator dict or None."""
    return cache.get(f"indicators:{symbol.upper()}")

def cache_indicators(symbol: str, data: dict, ttl: int = TTL_INDICATORS):
    """Cache computed indicators."""
    cache.set(f"indicators:{symbol.upper()}", data, timeout=ttl)

def get_cached_ohlcv(symbol: str) -> dict | None:
    """Returns cached latest OHLCV dict or None."""
    return cache.get(f"ohlcv:{symbol.upper()}")

def cache_ohlcv(symbol: str, data: dict, ttl: int = TTL_OHLCV):
    """Cache latest OHLCV."""
    cache.set(f"ohlcv:{symbol.upper()}", data, timeout=ttl)

def track_llm_tokens(provider: str, tokens: int):
    """
    Accumulate daily token usage per LLM provider.
    Cache key: 'llm_tokens_today:{provider}', TTL 86400.
    Logs WARNING when usage exceeds 80% of daily limit.
    Daily limits: groq=500000, google_ai=1500000,
                  openrouter=50000, ollama=999999999
    """
    LIMITS = {
        "groq": 500_000,
        "google_ai": 1_500_000,
        "openrouter": 50_000,
        "ollama": 999_999_999,
    }
    key = f"llm_tokens_today:{provider}"
    current = cache.get(key, 0)
    new_total = current + tokens
    cache.set(key, new_total, timeout=86400)
    limit = LIMITS.get(provider, 100_000)
    if new_total > limit * 0.8:
        import logging
        logging.getLogger('nepse_rag').warning(
            f"LLM token warning: {provider} at {new_total}/{limit} "
            f"({new_total/limit*100:.0f}%)"
        )

def get_provider_token_usage(provider: str) -> int:
    """Returns total tokens used today for a provider."""
    return cache.get(f"llm_tokens_today:{provider}", 0)

def is_llm_provider_exhausted(provider: str) -> bool:
    """Returns True if provider is marked rate-limited."""
    return bool(cache.get(f"{provider}_exhausted"))

def mark_llm_provider_exhausted(provider: str, ttl: int = 3600):
    """Marks LLM provider as rate-limited for TTL seconds."""
    cache.set(f"{provider}_exhausted", True, timeout=ttl)

def is_search_provider_exhausted(provider: str) -> bool:
    """Returns True if search provider is marked exhausted."""
    return bool(cache.get(f"{provider}_exhausted"))

def mark_search_provider_exhausted(provider: str, ttl: int = 3600):
    """Marks search provider as exhausted for TTL seconds."""
    cache.set(f"{provider}_exhausted", True, timeout=ttl)


# ── RAG Cache Helpers ─────────────────────────────────────────

TTL_VECTOR_RAG = 1800   # 30 minutes
TTL_GRAPH_RAG  = 3600   # 1 hour


def _vector_rag_key(question: str) -> str:
    """MD5 hash of normalized question for vector RAG cache."""
    raw = question.lower().strip()
    return "vrag:" + hashlib.md5(raw.encode()).hexdigest()


def get_cached_vector_rag(question: str) -> list | None:
    """Returns cached vector RAG results or None on miss."""
    return cache.get(_vector_rag_key(question))


def cache_vector_rag(question: str, results: list,
                     ttl: int = TTL_VECTOR_RAG):
    """Cache vector RAG retrieval results."""
    cache.set(_vector_rag_key(question), results, timeout=ttl)


def get_cached_graph_rag(symbol: str) -> dict | None:
    """Returns cached graph RAG results or None on miss."""
    return cache.get(f"graph_rag:{symbol.upper()}")


def cache_graph_rag(symbol: str, results: dict,
                    ttl: int = TTL_GRAPH_RAG):
    """Cache graph RAG retrieval results."""
    cache.set(f"graph_rag:{symbol.upper()}", results, timeout=ttl)


def get_cached_history(symbol: str, days: int) -> list | None:
    """Returns cached history list or None."""
    return cache.get(f"history:{symbol.upper()}:{days}")


def cache_history(symbol: str, days: int, data: list,
                  ttl: int = TTL_OHLCV):
    """Cache recent history data."""
    cache.set(f"history:{symbol.upper()}:{days}", data, timeout=ttl)


def get_cached_symbols() -> list | None:
    """Returns cached symbols list or None."""
    return cache.get("all_symbols")


def cache_symbols(data: list, ttl: int = TTL_SYMBOLS):
    """Cache all symbols list."""
    cache.set("all_symbols", data, timeout=ttl)


def get_cached_symbol_exists(symbol: str) -> bool | None:
    """Returns cached symbol existence check or None."""
    return cache.get(f"sym_exists:{symbol.upper()}")


def cache_symbol_exists(symbol: str, exists: bool, ttl: int = TTL_NEWS):
    """Cache symbol existence check."""
    cache.set(f"sym_exists:{symbol.upper()}", exists, timeout=ttl)
