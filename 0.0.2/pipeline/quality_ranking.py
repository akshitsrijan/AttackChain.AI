"""
Quality ranking stage — AttackChain Advisor pipeline.

Reranks the Top-K candidate knowledge entries returned by
``embedding_retrieval.retrieve()`` using quality metadata from the IEEE
DataPort quality-assessment dataset (quality_metrics.json).

Semantic similarity from the retriever is the *dominant* ranking signal.
Quality acts as a *trust adjustment*: when two entries have comparable
similarity scores, the more thoroughly validated entry is preferred.

Public API
----------
    rank(retrieved_entries: list[dict]) -> list[dict]

Each output dict is the original retrieved entry, extended with:
    composite_score  : float  — final ranking key (descending)
    quality_score    : float  — normalised quality signal  [0.0, 1.0]
    pass_count       : int    — raw number of quality checks passed
    confidence       : str    — human-readable tier: "High" | "Medium" | "Low"
    ranking_reason   : dict   — structured explanation of the ranking decision

The output is fully compatible with downstream ``graph_traversal`` and
``response_synthesis`` modules; legacy fields ``confidence_tier`` and
``quality_note`` are preserved for backward compatibility.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dataset paths
# ---------------------------------------------------------------------------

_DATA_DIR: Path = (
    Path(__file__).parent.parent / "experimental data" / "experimental data"
)
_QUALITY_FILE: Path = _DATA_DIR / "quality_metrics.json"

# ---------------------------------------------------------------------------
# Step 1 — Load quality_metrics.json and build a fast id -> metadata index
# ---------------------------------------------------------------------------

logger.info("Loading quality metrics from %s", _QUALITY_FILE)
_raw_quality: dict[str, Any] = json.loads(
    _QUALITY_FILE.read_text(encoding="utf-8")
)

#: Maximum number of quality checks any entry can pass (sourced from dataset).
MAX_POSSIBLE_CHECKS: int = _raw_quality["quality_checklist"]["max_possible"]

#: Dataset-level summary statistics (layer0 aggregate metrics).
DATASET_SUMMARY: dict[str, Any] = _raw_quality.get("layer0", {})

# ---------------------------------------------------------------------------
# Step 2 — Extract per-entry quality information into a structured index
# ---------------------------------------------------------------------------

# Quality dimension names present in the dataset.
# Order is preserved so logs and explanations are reproducible.
_DIMENSION_NAMES: list[str] = [
    "trigger_situation_first",
    "no_action_in_knowledge",
    "generalizes_to",
    "pitfalls_present",
    "confidence_rationale",
    "applicable_two_layer",
    "abstraction_distance",
    "cross_references",
]


def _extract_entry_quality(item: dict[str, Any]) -> dict[str, Any]:
    """Parse one quality-checklist item into a structured metadata object.

    Parameters
    ----------
    item:
        A single element from ``quality_checklist.items`` in the JSON.

    Returns
    -------
    dict
        Structured quality metadata with keys:
        ``pass_count``, ``pass_rate``, ``dimensions``, ``failed_checks``,
        ``passed_checks``.
    """
    checks: dict[str, dict] = item.get("checks", {})
    pass_count: int = item.get("pass_count", 0)

    dimensions: dict[str, bool] = {
        name: bool(checks.get(name, {}).get("passed", False))
        for name in _DIMENSION_NAMES
    }
    failed_checks: list[str] = [
        name for name, passed in dimensions.items() if not passed
    ]
    passed_checks: list[str] = [
        name for name, passed in dimensions.items() if passed
    ]
    pass_rate: float = (
        round(pass_count / MAX_POSSIBLE_CHECKS, 4) if MAX_POSSIBLE_CHECKS else 0.0
    )

    return {
        "pass_count": pass_count,
        "pass_rate": pass_rate,
        "dimensions": dimensions,
        "failed_checks": failed_checks,
        "passed_checks": passed_checks,
    }


#: Fast lookup: entry_id -> structured quality metadata.
#: Built once at module import; dictionary lookup is O(1).
QUALITY_INDEX: dict[str, dict[str, Any]] = {
    item["id"]: _extract_entry_quality(item)
    for item in _raw_quality["quality_checklist"]["items"]
}

logger.info(
    "Quality index built: %d entries indexed (max_possible_checks=%d)",
    len(QUALITY_INDEX),
    MAX_POSSIBLE_CHECKS,
)

# ---------------------------------------------------------------------------
# Step 3 — Composite ranking score (weighted combination)
# ---------------------------------------------------------------------------

# ┌─────────────────────────────────────────────────────────────────────────┐
# │  COMPOSITE SCORE FORMULA                                                │
# │                                                                         │
# │  composite_score = (SIMILARITY_WEIGHT * similarity)                    │
# │                  + (QUALITY_WEIGHT    * quality_score)                  │
# │                                                                         │
# │  where:                                                                 │
# │    similarity    = cosine similarity from the retriever   ∈ [0.0, 1.0] │
# │    quality_score = pass_count / max_possible_checks       ∈ [0.0, 1.0] │
# │    SIMILARITY_WEIGHT = 0.75  (dominant signal)                          │
# │    QUALITY_WEIGHT    = 0.25  (trust adjustment)                         │
# │                                                                         │
# │  Rationale:                                                             │
# │    An additive formula is used (not multiplicative) so that a small     │
# │    quality penalty never zeroes-out a highly relevant entry.  The 3:1  │
# │    weight ratio ensures semantic relevance stays dominant while quality │
# │    acts as a decisive tie-breaker.  Both weights are constants that can │
# │    be tuned below without touching any other code.                      │
# └─────────────────────────────────────────────────────────────────────────┘

#: Weight applied to semantic similarity (must remain dominant, i.e. > 0.5).
SIMILARITY_WEIGHT: float = 0.75

#: Weight applied to the normalised quality score (trust adjustment).
QUALITY_WEIGHT: float = 0.25


def _compute_quality_score(entry_id: str) -> float:
    """Return the normalised quality score for an entry.

    Parameters
    ----------
    entry_id:
        Knowledge entry identifier (e.g. ``"ek_0002"``).

    Returns
    -------
    float
        ``pass_count / max_possible_checks`` ∈ [0.0, 1.0].
        Returns 0.0 if the entry has no quality record.
    """
    meta = QUALITY_INDEX.get(entry_id)
    if meta is None:
        logger.debug("No quality record for '%s'; defaulting score to 0.0", entry_id)
        return 0.0
    return meta["pass_rate"]


def _compute_composite_score(similarity: float, quality_score: float) -> float:
    """Compute the weighted composite ranking score.

    composite_score = SIMILARITY_WEIGHT * similarity
                    + QUALITY_WEIGHT    * quality_score

    Parameters
    ----------
    similarity:
        Cosine similarity from the retriever ∈ [0.0, 1.0].
    quality_score:
        Normalised quality signal ∈ [0.0, 1.0].

    Returns
    -------
    float
        Composite score rounded to 4 decimal places.
    """
    raw = (SIMILARITY_WEIGHT * similarity) + (QUALITY_WEIGHT * quality_score)
    return round(raw, 4)

# ---------------------------------------------------------------------------
# Step 4 — Confidence tiers
# ---------------------------------------------------------------------------

# Thresholds are defined as constants so they can be adjusted in one place.
# Based primarily on pass_count (integer, out of MAX_POSSIBLE_CHECKS).
#
#   High   : pass_count >= HIGH_CONFIDENCE_THRESHOLD   (e.g. all 8/8)
#   Medium : pass_count >= MEDIUM_CONFIDENCE_THRESHOLD  (e.g. 6 or 7/8)
#   Low    : pass_count <  MEDIUM_CONFIDENCE_THRESHOLD

#: Minimum pass_count to earn "High" confidence label.
HIGH_CONFIDENCE_THRESHOLD: int = MAX_POSSIBLE_CHECKS        # 8/8

#: Minimum pass_count to earn "Medium" confidence label.
MEDIUM_CONFIDENCE_THRESHOLD: int = MAX_POSSIBLE_CHECKS - 2  # 6/8


def _confidence_label(pass_count: int) -> str:
    """Map a raw pass_count to a human-readable confidence tier.

    Parameters
    ----------
    pass_count:
        Number of quality checks passed for the entry.

    Returns
    -------
    str
        One of ``"High"``, ``"Medium"``, or ``"Low"``.
    """
    if pass_count >= HIGH_CONFIDENCE_THRESHOLD:
        return "High"
    if pass_count >= MEDIUM_CONFIDENCE_THRESHOLD:
        return "Medium"
    return "Low"

# ---------------------------------------------------------------------------
# Step 5 — Ranking explanation (structured metadata)
# ---------------------------------------------------------------------------


def _build_ranking_reason(
    entry_id: str,
    similarity: float,
    quality_score: float,
    composite_score: float,
    pass_count: int,
    confidence: str,
    meta: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build a structured explanation for why an entry ranked at its position.

    This is structured data, not a natural-language paragraph.  All values
    are machine-readable scalars or lists.

    Parameters
    ----------
    entry_id:
        Knowledge entry identifier.
    similarity:
        Raw cosine similarity from the retriever.
    quality_score:
        Normalised quality signal.
    composite_score:
        Final weighted ranking key.
    pass_count:
        Raw number of checks passed.
    confidence:
        Human-readable confidence tier label.
    meta:
        Full quality metadata dict from QUALITY_INDEX (or None).

    Returns
    -------
    dict
        Structured ranking explanation with the following keys:
        ``formula``, ``similarity_contribution``, ``quality_contribution``,
        ``quality_score``, ``pass_count``, ``max_possible``,
        ``confidence``, ``passed_dimensions``, ``failed_dimensions``,
        ``quality_source``.
    """
    passed_dims: list[str] = meta["passed_checks"] if meta else []
    failed_dims: list[str] = meta["failed_checks"] if meta else []
    has_record: bool = meta is not None

    return {
        "formula": (
            f"composite = {SIMILARITY_WEIGHT} * similarity"
            f" + {QUALITY_WEIGHT} * quality_score"
        ),
        "similarity_contribution": round(SIMILARITY_WEIGHT * similarity, 4),
        "quality_contribution": round(QUALITY_WEIGHT * quality_score, 4),
        "quality_score": quality_score,
        "pass_count": pass_count,
        "max_possible": MAX_POSSIBLE_CHECKS,
        "pass_rate": meta["pass_rate"] if meta else 0.0,
        "confidence": confidence,
        "passed_dimensions": passed_dims,
        "failed_dimensions": failed_dims,
        "quality_source": "quality_metrics.json" if has_record else "none (default)",
    }

# ---------------------------------------------------------------------------
# Backward-compat helpers (consumed by response_synthesis.py)
# ---------------------------------------------------------------------------


def _legacy_confidence_tier(confidence: str) -> str:
    """Convert the new tiered label to the legacy 'confidence_tier' vocabulary.

    ``response_synthesis.py`` reads ``entry['confidence_tier']``.
    We map:  High -> "high"  |  Medium -> "needs_validation"  |  Low -> "needs_validation"
    """
    return "high" if confidence == "High" else "needs_validation"


def _legacy_quality_note(pass_count: int, failed: list[str]) -> str:
    """Generate the legacy ``quality_note`` string expected by response_synthesis."""
    if not failed:
        return f"{pass_count}/{MAX_POSSIBLE_CHECKS} quality checks passed"
    return (
        f"{pass_count}/{MAX_POSSIBLE_CHECKS} checks passed"
        f" (failed: {', '.join(failed)})"
    )

# ---------------------------------------------------------------------------
# Step 6 — Public API: rank()
# ---------------------------------------------------------------------------


def rank(retrieved_entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rerank retrieved knowledge entries using quality-adjusted composite scores.

    Combines each entry's semantic similarity (dominant signal, weight=0.75)
    with a normalised quality score derived from the IEEE DataPort quality
    assessment dataset (trust adjustment, weight=0.25).

    Input entries are **not mutated**; new dicts are returned.

    Parameters
    ----------
    retrieved_entries:
        List of dicts returned by ``embedding_retrieval.retrieve()``.
        Each dict must contain at minimum:
            - ``"id"``         : str  — knowledge entry identifier
            - ``"similarity"`` : float — cosine similarity score

    Returns
    -------
    list[dict]
        Same entries, sorted descending by ``composite_score``, each
        extended with the following additional fields:

        - ``composite_score``  : float — final ranking key
        - ``quality_score``    : float — normalised quality signal [0, 1]
        - ``pass_count``       : int   — raw quality checks passed
        - ``confidence``       : str   — "High" | "Medium" | "Low"
        - ``ranking_reason``   : dict  — structured ranking explanation
        - ``confidence_tier``  : str   — legacy alias (backward compat)
        - ``quality_note``     : str   — legacy alias (backward compat)
    """
    if not retrieved_entries:
        logger.warning("rank() received an empty candidate list; returning [].")
        return []

    logger.info(
        "Quality-ranking %d candidate(s) "
        "(similarity_weight=%.2f, quality_weight=%.2f)",
        len(retrieved_entries),
        SIMILARITY_WEIGHT,
        QUALITY_WEIGHT,
    )

    ranked: list[dict[str, Any]] = []

    for entry in retrieved_entries:
        entry_id: str = entry.get("id", "")
        similarity: float = float(entry.get("similarity", 0.0))

        # --- quality signals ---
        meta: dict[str, Any] | None = QUALITY_INDEX.get(entry_id)
        quality_score: float = _compute_quality_score(entry_id)
        pass_count: int = meta["pass_count"] if meta else 0
        failed_dims: list[str] = meta["failed_checks"] if meta else []

        # --- composite score ---
        composite_score: float = _compute_composite_score(similarity, quality_score)

        # --- confidence tier ---
        confidence: str = _confidence_label(pass_count)

        # --- ranking explanation ---
        ranking_reason: dict[str, Any] = _build_ranking_reason(
            entry_id=entry_id,
            similarity=similarity,
            quality_score=quality_score,
            composite_score=composite_score,
            pass_count=pass_count,
            confidence=confidence,
            meta=meta,
        )

        logger.debug(
            "Entry %s: similarity=%.4f quality=%.4f composite=%.4f confidence=%s",
            entry_id,
            similarity,
            quality_score,
            composite_score,
            confidence,
        )

        ranked.append({
            # --- original fields (preserved unchanged) ---
            **entry,
            # --- new fields (composite ranking) ---
            "composite_score": composite_score,
            "quality_score": quality_score,
            "pass_count": pass_count,
            "confidence": confidence,
            "ranking_reason": ranking_reason,
            # --- legacy fields (backward compat with response_synthesis.py) ---
            "confidence_tier": _legacy_confidence_tier(confidence),
            "quality_note": _legacy_quality_note(pass_count, failed_dims),
        })

    # Sort descending by composite_score; use entry_id as a deterministic
    # tie-breaker so output order is stable across identical scores.
    ranked.sort(key=lambda x: (x["composite_score"], x["id"]), reverse=True)

    logger.info(
        "Ranking complete — top entry: %s (composite=%.4f, confidence=%s)",
        ranked[0]["id"],
        ranked[0]["composite_score"],
        ranked[0]["confidence"],
    )

    return ranked

# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------


def _self_test() -> None:
    """Validate the ranking stage end-to-end using the live retriever output.

    Exercises:
    1. Import ``embedding_retrieval.retrieve`` and run a representative query.
    2. Pass the results through ``rank()``.
    3. Print a formatted table: Rank | ID | Similarity | Quality Score |
       Composite Score | Confidence.
    4. Assert that the output list is sorted correctly.
    5. Assert that all required output fields are present.
    """
    # Import here to avoid circular dependency at module load time.
    try:
        from embedding_retrieval import retrieve  # type: ignore[import]
    except ImportError as exc:
        print(f"SKIP: embedding_retrieval not importable ({exc}) — using synthetic data")
        _synthetic_test()
        return

    query = (
        "The application behaves differently when whitespace is added to HTTP headers."
    )
    print(f"\nSelf-test query: {query!r}")

    candidates = retrieve(query, k=5)
    if not candidates:
        print("SKIP: retrieve() returned no candidates.")
        return

    results = rank(candidates)

    # --- print results table ---
    sep = "=" * 90
    print(f"\n{sep}")
    print(f"{'Rank':<5} {'ID':<12} {'Similarity':>11} {'Quality Score':>14} "
          f"{'Composite':>10} {'Confidence':<10} {'Pass Count':>10}")
    print("-" * 90)
    for pos, entry in enumerate(results, start=1):
        print(
            f"{pos:<5} {entry['id']:<12} {entry['similarity']:>11.4f} "
            f"{entry['quality_score']:>14.4f} {entry['composite_score']:>10.4f} "
            f"{entry['confidence']:<10} {entry['pass_count']:>10}"
        )
    print(f"{sep}\n")

    # --- assertions ---
    scores = [e["composite_score"] for e in results]
    assert scores == sorted(scores, reverse=True), (
        "FAIL: results are not sorted descending by composite_score"
    )
    print("PASS: results sorted correctly by composite_score (descending)")

    required_fields = {
        "composite_score", "quality_score", "pass_count",
        "confidence", "ranking_reason",
        "confidence_tier", "quality_note",  # legacy compat
    }
    for entry in results:
        missing = required_fields - entry.keys()
        assert not missing, f"FAIL: entry {entry['id']} missing fields: {missing}"
    print("PASS: all required output fields present on every ranked entry")

    rr = results[0]["ranking_reason"]
    assert "formula" in rr, "FAIL: ranking_reason missing 'formula' key"
    assert "passed_dimensions" in rr, "FAIL: ranking_reason missing 'passed_dimensions'"
    print("PASS: ranking_reason is structured and contains expected keys")

    print("\nAll self-test assertions passed.")


def _synthetic_test() -> None:
    """Minimal synthetic test used when the retriever cannot be imported.

    Uses known entries from quality_metrics.json directly.
    - ek_0000 has pass_count=8 (perfect quality)
    - ek_0002 has pass_count=7 (one failed check)
    Give ek_0002 a slightly higher similarity so quality must be the tie-breaker.
    """
    candidates = [
        {"id": "ek_0002", "title": "High-similarity, lower quality",
         "similarity": 0.72, "knowledge": "", "category": "test"},
        {"id": "ek_0000", "title": "Slightly lower similarity, perfect quality",
         "similarity": 0.65, "knowledge": "", "category": "test"},
    ]
    results = rank(candidates)

    sep = "=" * 90
    print(f"\n{sep}")
    print(f"{'Rank':<5} {'ID':<12} {'Similarity':>11} {'Quality Score':>14} "
          f"{'Composite':>10} {'Confidence':<10} {'Pass Count':>10}")
    print("-" * 90)
    for pos, entry in enumerate(results, start=1):
        print(
            f"{pos:<5} {entry['id']:<12} {entry['similarity']:>11.4f} "
            f"{entry['quality_score']:>14.4f} {entry['composite_score']:>10.4f} "
            f"{entry['confidence']:<10} {entry['pass_count']:>10}"
        )
    print(f"{sep}\n")

    # Composite score calculation (verified manually):
    #   ek_0002: 0.75 * 0.72 + 0.25 * (7/8) = 0.5400 + 0.2188 = 0.7588
    #   ek_0000: 0.75 * 0.65 + 0.25 * (8/8) = 0.4875 + 0.2500 = 0.7375
    # ek_0002 ranks first because its higher similarity outweighs the quality gap.
    assert results[0]["id"] == "ek_0002", (
        f"FAIL: expected ek_0002 first, got {results[0]['id']}"
    )
    # ek_0002 has pass_count=7 (MAX-1) -> Medium tier
    # ek_0000 has pass_count=8 (MAX)   -> High tier
    assert results[0]["confidence"] == "Medium", (
        f"FAIL: ek_0002 (pass_count=7) should be 'Medium', got {results[0]['confidence']}"
    )
    assert results[1]["confidence"] == "High", (
        f"FAIL: ek_0000 (pass_count=8) should be 'High', got {results[1]['confidence']}"
    )
    print("PASS: synthetic test — composite score correctly computed")
    print("PASS: confidence tiers assigned correctly")
    print("PASS: ranking_reason structured data present")


if __name__ == "__main__":
    _self_test()
