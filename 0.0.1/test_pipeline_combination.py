"""
Tests the A -> B -> C combination logic using static fixtures from
test_fixtures.json, without calling the LLM or any teammate's real module.

Run: python test_pipeline_combination.py
"""

import json
from pathlib import Path

FIXTURES = json.loads((Path(__file__).parent / "test_fixtures.json").read_text(encoding="utf-8"))


def fake_retrieve(observation: str) -> list[dict]:
    """Stand-in for Person A, returns the fixture instead of computing embeddings."""
    assert observation == FIXTURES["observation"], "fixture only matches the sample observation"
    return FIXTURES["person_a_output"]


def fake_rank(candidates: list[dict]) -> list[dict]:
    """Stand-in for Person B, returns the fixture's pre-ranked output."""
    return FIXTURES["person_b_output"]


def fake_get_chain_context(entry_id: str) -> dict:
    """Stand-in for Person C, picks the matching fixture by entry id."""
    if entry_id == FIXTURES["person_c_output"]["for_entry_id"]:
        return FIXTURES["person_c_output"]
    if entry_id == FIXTURES["person_c_output_truncated_example"]["for_entry_id"]:
        return FIXTURES["person_c_output_truncated_example"]
    return {"next": [], "prev": [], "truncated_ids": []}


def combine(observation: str) -> dict:
    """The same combination logic main.py uses, isolated for testing."""
    candidates = fake_retrieve(observation)
    ranked = fake_rank(candidates)
    top_entry = ranked[0]
    chain_context = fake_get_chain_context(top_entry["id"])

    return {
        "matched_entry_id": top_entry["id"],
        "matched_entry_title": top_entry["title"],
        "confidence_tier": top_entry["confidence_tier"],
        "quality_note": top_entry["quality_note"],
        "chain_next": [n["id"] for n in chain_context["next"]],
        "chain_prev": [p["id"] for p in chain_context["prev"]],
        "truncated_ids": chain_context["truncated_ids"],
    }


def test_top_match_is_ek_0002():
    result = combine(FIXTURES["observation"])
    assert result["matched_entry_id"] == "ek_0002", result
    print("PASS: top match is ek_0002")


def test_chain_surfaces_ek_0003():
    result = combine(FIXTURES["observation"])
    assert "ek_0003" in result["chain_next"], result
    print("PASS: chain surfaces ek_0003 as next step")


def test_confidence_tier_propagates():
    result = combine(FIXTURES["observation"])
    assert result["confidence_tier"] == "high", result
    print("PASS: confidence tier propagates correctly")


def test_truncated_chain_handling():
    chain = fake_get_chain_context("ek_0016")
    assert chain["truncated_ids"] == ["ek_0067"], chain
    print("PASS: truncated out-of-range chain id is flagged, not silently dropped")


if __name__ == "__main__":
    test_top_match_is_ek_0002()
    test_chain_surfaces_ek_0003()
    test_confidence_tier_propagates()
    test_truncated_chain_handling()

    print("\nFinal combined output:")
    print(json.dumps(combine(FIXTURES["observation"]), indent=2))
