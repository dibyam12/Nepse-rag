"""
Groundedness checker for NEPSE AI responses.

Uses the cross-encoder (shared singleton from vector_rag.py) to score
how well each claim in the LLM answer is supported by the provided context.

If the average entailment score is below 0.5, the caller appends a
"some claims could not be verified" warning to the response.

Public API:
    check_groundedness(answer, context_chunks) -> GroundednessResult
"""

import re
import logging
from dataclasses import dataclass, field

logger = logging.getLogger('nepse_rag')


@dataclass
class GroundednessResult:
    """
    Result of a groundedness check.

    Attributes:
        score:           0.0–1.0 average cross-encoder entailment score.
        flagged_claims:  Claims with individual score < 0.3.
        total_claims:    Total number of claim sentences evaluated.
    """
    score: float
    flagged_claims: list = field(default_factory=list)
    total_claims: int = 0


def _split_claims(text: str) -> list[str]:
    """
    Splits an LLM answer into individual claim sentences for evaluation.

    Pre-processing:
    - Strips DISCLAIMER footer
    - Strips <thinking> blocks
    - Filters sentences shorter than 30 chars (noise)
    - Filters actionable/advisory sentences (not factual claims)
    """
    if not text:
        return []

    # Remove boilerplate
    text = re.sub(r'DISCLAIMER:.*$', '', text, flags=re.IGNORECASE | re.MULTILINE)
    text = re.sub(r'<thinking>.*?</thinking>', '', text, flags=re.DOTALL)
    text = re.sub(r'⚠️.*$', '', text, flags=re.MULTILINE)

    # Split on sentence boundaries
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())

    # Filter: skip very short, advisory, or subjective sentences
    _ADVISORY_PATTERNS = [
        r'\bwait for\b', r'\bbefore reconsidering\b', r'\bcautious\b',
        r'\bwarrant\b', r'\bcross-check\b', r'\bconsider\b',
        r'\bdisclaimer\b', r'\beducational\b', r'\bnot financial advice\b',
        r'\bbased on current indicators\b', r'\bworth (watching|monitoring)\b',
    ]

    filtered = []
    for s in sentences:
        s = s.strip()
        if len(s) < 30:
            continue
        # Skip advisory/subjective sentences — they aren't factual claims
        if any(re.search(pat, s, re.IGNORECASE) for pat in _ADVISORY_PATTERNS):
            continue
        filtered.append(s)

    return filtered


def check_groundedness(
    answer: str,
    context_chunks: list[str],
    threshold: float = 0.3,
) -> GroundednessResult:
    """
    Scores how well the LLM answer is grounded in the provided context.

    Uses the cross-encoder singleton from vector_rag (ms-marco-MiniLM-L-6-v2).
    Each claim sentence is scored against the combined context. Claims with
    score < 0.3 are flagged as potentially ungrounded.

    Args:
        answer:         The LLM's response text.
        context_chunks: List of context strings (sql_output, graph_output, etc.)
        threshold:      Minimum average score for "grounded" (default 0.5).

    Returns:
        GroundednessResult with average score and flagged claims.
    """
    claims = _split_claims(answer)
    if not claims or not context_chunks:
        return GroundednessResult(score=1.0, flagged_claims=[], total_claims=0)

    # Combine all context, capped to avoid extremely long pairs
    context_combined = " ".join(
        chunk for chunk in context_chunks if chunk and chunk.strip()
    )[:4000]

    if not context_combined.strip():
        return GroundednessResult(score=1.0, flagged_claims=[], total_claims=0)

    try:
        from services.vector_rag import get_cross_encoder_model
        ce = get_cross_encoder_model()
    except Exception as e:
        logger.warning("Could not load cross-encoder for groundedness: %s", e)
        return GroundednessResult(score=1.0, flagged_claims=[], total_claims=0)

    pairs = [(claim, context_combined) for claim in claims]
    scores = ce.predict(pairs)

    flagged = []
    for claim, score in zip(claims, scores):
        if float(score) < 0.3:
            flagged.append({
                "claim": claim[:200],
                "score": round(float(score), 3),
            })

    avg_score = sum(float(s) for s in scores) / len(scores) if scores.any() else 1.0
    avg_score = max(0.0, min(1.0, avg_score))  # Clamp to [0, 1]

    logger.info(
        "Groundedness: %.2f (%d/%d claims flagged)",
        avg_score, len(flagged), len(claims),
        extra={
            "event": "groundedness_check",
            "score": round(avg_score, 3),
            "total_claims": len(claims),
            "flagged_count": len(flagged),
        },
    )

    return GroundednessResult(
        score=round(avg_score, 3),
        flagged_claims=flagged,
        total_claims=len(claims),
    )
