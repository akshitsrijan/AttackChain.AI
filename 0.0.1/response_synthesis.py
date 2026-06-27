"""
Response synthesis stage.

Combines the matched-and-ranked knowledge entry with its chain context into
a structured response template, then drives a local LLM to turn that
structured data into a readable advisory for the researcher. The LLM is
grounded strictly in the supplied entry and chain data — it is not asked to
introduce information beyond what retrieval, ranking, and graph traversal
have already surfaced.
"""

import json
import os
import urllib.request

OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5vl:3b")


def build_response_template(top_entry: dict, chain_context: dict) -> dict:
    """Combine the top-ranked entry and its chain context into one response shape."""
    matched = {
        "id": top_entry["id"],
        "title": top_entry["title"],
    }

    reasoning = {
        "similarity_score": top_entry.get("similarity"),
        "confidence_tier": top_entry.get("confidence_tier"),
        "quality_note": top_entry.get("quality_note"),
    }

    return {
        "matched": matched,
        "reasoning": reasoning,
        "pitfalls": top_entry.get("pitfalls", []),
        "confidence": top_entry.get("confidence"),
        "shelf_life": top_entry.get("shelf_life"),
        "chain": chain_context,
    }


def _call_llm(prompt: str, system: str | None = None) -> str:
    payload = {"model": OLLAMA_MODEL, "prompt": prompt, "system": system or "", "stream": False}
    req = urllib.request.Request(
        "http://localhost:11434/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))["response"]


def synthesize(observation: str, top_entry: dict, chain_context: dict) -> str:
    """Generate the final natural-language advisory from the structured response template."""
    system = (
        "You are AttackChain Advisor. Ground your answer ONLY in the provided "
        "entry and chain data. Explain: (1) why this entry matched the "
        "observation, (2) the pitfall to watch for, (3) confidence + shelf-life, "
        "(4) the full attack chain (next AND previous steps if present)."
    )
    next_text = "\n".join(f"- {n['id']}" for n in chain_context.get("next", [])) or "none found"
    prev_text = "\n".join(f"- {p['id']}" for p in chain_context.get("prev", [])) or "none found"

    prompt = f"""Researcher observation:
{observation}

Matched entry: {top_entry['id']} — {top_entry['title']}
Similarity score: {top_entry.get('similarity')}
Confidence tier: {top_entry.get('confidence_tier')}
Quality note: {top_entry.get('quality_note')}

knowledge: {top_entry['knowledge']}
abstracted_pattern: {top_entry['abstracted_pattern']['pattern']}
pitfalls: {top_entry['pitfalls']}
confidence: {top_entry['confidence']} ({top_entry['confidence_rationale']})
shelf_life: {top_entry['shelf_life']}

Chain — next steps:
{next_text}

Chain — previous steps (what leads here):
{prev_text}

Write the advisory response."""
    return _call_llm(prompt, system=system)


def _test_template_shape() -> None:
    """Sanity check: the response template carries through every field a consumer needs."""
    top_entry = {
        "id": "ek_0002",
        "title": "Gopher Protocol CRLF Tolerance",
        "similarity": 0.87,
        "confidence_tier": "high",
        "quality_note": "8/8 quality checks passed",
        "pitfalls": ["Assuming all protocol handlers share the same sanitization as http/https"],
        "confidence": "high",
        "shelf_life": "semi-permanent",
    }
    chain_context = {"next": [{"id": "ek_0003"}], "prev": [], "truncated_ids": []}

    response = build_response_template(top_entry, chain_context)
    assert response["matched"]["id"] == "ek_0002"
    assert response["reasoning"]["confidence_tier"] == "high"
    assert response["chain"]["next"][0]["id"] == "ek_0003"
    print("PASS: response template carries matched/reasoning/pitfalls/chain fields")
    print(json.dumps(response, indent=2))


if __name__ == "__main__":
    _test_template_shape()
