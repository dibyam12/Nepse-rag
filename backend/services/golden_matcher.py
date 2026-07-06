"""
services/golden_matcher.py
Golden Prompt Matcher for NEPSE AI Demo Mode.

Matches user queries against curated golden prompt patterns using
regex and fuzzy token matching. When matched, returns the response
template and slot rules that guide the LLM to produce a flawless,
demo-quality response.

NOT a response cache — the agent still runs the full RAG pipeline.
The golden prompt only adds an 'ideal_structure' hint to the LLM prompt,
ensuring consistent structure and tone while actual numbers come from live data.

Usage:
    from services.golden_matcher import match_golden
    match = match_golden("How is NABIL performing?", symbols=["NABIL"])
    if match:
        prompt = build_rag_prompt(..., golden_match=match)
"""

import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from difflib import SequenceMatcher

logger = logging.getLogger("nepse_rag")

GOLDEN_FILE = Path(__file__).parent / "golden_prompts.json"

# Similarity threshold for fuzzy matching (0.0 - 1.0)
FUZZY_THRESHOLD = 0.7


@lru_cache(maxsize=1)
def _load_golden_prompts() -> tuple:
    """Load golden prompts from JSON. Cached — reloads only once per process.
    Returns a tuple (for hashability with lru_cache)."""
    if not GOLDEN_FILE.exists():
        logger.warning("golden_prompts.json not found at %s", GOLDEN_FILE)
        return ()
    try:
        with open(GOLDEN_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        logger.info("Loaded %d golden prompts from %s", len(data), GOLDEN_FILE)
        return tuple(data)
    except Exception as e:
        logger.warning("Failed to load golden_prompts.json: %s", e)
        return ()


def load_golden_prompts() -> list[dict]:
    """Returns golden prompts as a list."""
    return list(_load_golden_prompts())


def _pattern_to_regex(pattern: str) -> str:
    """Convert a golden prompt pattern to a regex.
    Replaces {SYMBOL}, {SYM1}, {SYM2}, {N}, {YEAR}, {INDICATOR}, {SECTOR}
    with regex wildcards that match 1+ non-whitespace characters.
    """
    # Escape the pattern first (for dots, brackets, etc.)
    escaped = re.escape(pattern.lower())
    # Then un-escape the placeholder patterns
    escaped = re.sub(r'\\{[^}]+\\}', r'\\S+', escaped)
    return escaped


def _normalize_pattern(pattern: str, symbols: list[str]) -> str:
    """Normalize a pattern by substituting actual symbols for placeholders."""
    normalized = pattern.lower()
    if symbols:
        normalized = normalized.replace("{symbol}", symbols[0].lower())
        if len(symbols) > 1:
            normalized = normalized.replace("{sym1}", symbols[0].lower())
            normalized = normalized.replace("{sym2}", symbols[1].lower())
        # Also handle reverse order
        normalized = normalized.replace("{sym1}", symbols[0].lower())
        normalized = normalized.replace("{sym2}", symbols[-1].lower())
    # Remove remaining unresolved placeholders for fuzzy matching
    normalized = re.sub(r'\{[^}]+\}', '', normalized).strip()
    return normalized


def match_golden(question: str, symbols: list[str] = None) -> dict | None:
    """
    Match a user question against golden prompt patterns.

    Strategy:
    1. Full regex scan across ALL patterns/prompts (no fuzzy fallback yet)
    2. Only if no regex match found: full fuzzy scan with FUZZY_THRESHOLD

    This two-pass approach prevents an early fuzzy hit from shadowing a
    more specific regex pattern defined later in the file.

    Args:
        question: The user's input question.
        symbols: List of detected NEPSE symbols (e.g., ["NABIL", "NICA"]).

    Returns:
        The matching golden prompt dict, or None if no match.
    """
    prompts = load_golden_prompts()
    if not prompts:
        return None

    q_lower = question.lower().strip()
    symbols = symbols or []

    # ── Pass 1: Regex scan across ALL prompts ─────────────────────────────
    for prompt in prompts:
        for pattern in prompt.get("match_patterns", []):
            regex = _pattern_to_regex(pattern)
            try:
                if re.search(regex, q_lower):
                    logger.info(
                        "golden_matcher: regex match '%s' → id='%s'",
                        pattern, prompt["id"],
                    )
                    return prompt
            except re.error:
                pass  # Malformed regex — handled in pass 2

    # ── Pass 2: Fuzzy scan across ALL prompts ─────────────────────────────
    best_ratio = 0.0
    best_prompt = None

    for prompt in prompts:
        for pattern in prompt.get("match_patterns", []):
            normalized = _normalize_pattern(pattern, symbols)
            if not normalized:
                continue
            ratio = SequenceMatcher(None, q_lower, normalized).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_prompt = prompt

    if best_ratio >= FUZZY_THRESHOLD and best_prompt is not None:
        logger.info(
            "golden_matcher: fuzzy match (%.2f) → id='%s'",
            best_ratio, best_prompt["id"],
        )
        return best_prompt

    return None



def list_golden_ids() -> list[str]:
    """Returns all golden prompt IDs (for debugging/testing)."""
    return [p["id"] for p in load_golden_prompts()]
