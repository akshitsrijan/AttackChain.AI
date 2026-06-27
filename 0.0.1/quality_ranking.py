"""
Quality ranking stage.

Re-scores retrieval candidates by combining their similarity score with an
independent quality assessment of each knowledge entry, so that a strong
embedding match from a poorly-structured entry doesn't outrank a slightly
weaker match from a fully-validated one.
"""

import json
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "experimental data" / "experimental data"
QUALITY_FILE = DATA_DIR / "quality_metrics.json"

# Load the quality scorecard and build an id -> {pass_count, failed_checks} index.
_QUALITY = json.loads(QUALITY_FILE.read_text(encoding="utf-8"))
_MAX_CHECKS = _QUALITY["quality_checklist"]["max_possible"]

QUALITY_INDEX = {}
for _item in _QUALITY["quality_checklist"]["items"]:
    _failed = [name for name, c in _item["checks"].items() if not c["passed"]]
    QUALITY_INDEX[_item["id"]] = {
        "pass_count": _item["pass_count"],
        "failed_checks": _failed,
    }

# Composite score formula: similarity is discounted by how well-validated the
# entry is, rather than being sorted independently of quality.
#   composite_score = similarity * (pass_count / max_possible_checks)
QUALITY_WEIGHT_FORMULA = "composite_score = similarity * (pass_count / max_possible_checks)"


def _quality_weight(entry_id: str) -> float:
    q = QUALITY_INDEX.get(entry_id)
    if not q:
        return 0.0
    return q["pass_count"] / _MAX_CHECKS


def _confidence_tier(pass_count: int) -> str:
    """An entry only earns 'high' confidence if it passed every quality check."""
    return "high" if pass_count == _MAX_CHECKS else "needs_validation"


def _quality_note(entry_id: str) -> str:
    q = QUALITY_INDEX.get(entry_id)
    if not q:
        return "No quality data available."
    if not q["failed_checks"]:
        return f"{q['pass_count']}/{_MAX_CHECKS} quality checks passed"
    return f"{q['pass_count']}/{_MAX_CHECKS} checks passed (failed: {', '.join(q['failed_checks'])})"


def rank(candidates: list[dict]) -> list[dict]:
    """Public entry point: re-sort retrieval candidates by quality-adjusted score."""
    ranked = []
    for c in candidates:
        q = QUALITY_INDEX.get(c["id"], {"pass_count": 0, "failed_checks": []})
        composite_score = round(c.get("similarity", 0.0) * _quality_weight(c["id"]), 4)
        ranked.append({
            **c,
            "confidence_tier": _confidence_tier(q["pass_count"]),
            "quality_note": _quality_note(c["id"]),
            "composite_score": composite_score,
        })
    ranked.sort(key=lambda x: x["composite_score"], reverse=True)
    return ranked


def _test_ranked_output() -> None:
    """Sanity check: a perfect-quality entry should outrank a slightly-higher-similarity, lower-quality one."""
    candidates = [
        {"id": "ek_0002", "title": "high-similarity, weaker quality", "similarity": 0.68},
        {"id": "ek_0000", "title": "lower-similarity, perfect quality", "similarity": 0.6},
    ]
    ranked = rank(candidates)
    assert ranked[0]["id"] == "ek_0000", "perfect-quality entry should outrank lower-quality higher-similarity entry"
    assert ranked[0]["confidence_tier"] == "high"
    assert ranked[1]["confidence_tier"] == "needs_validation"
    print("PASS: composite score reorders by quality-discounted similarity")
    print("PASS: confidence tiers assigned correctly")
    for r in ranked:
        print(f"  {r['id']}: composite={r['composite_score']} tier={r['confidence_tier']} | {r['quality_note']}")


if __name__ == "__main__":
    _test_ranked_output()
