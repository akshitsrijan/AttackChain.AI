"""
AttackChain Advisor — RAG + graph-traversal pipeline over the experiential
knowledge base, backed by a free local LLM (Ollama).

Pipeline: Researcher input -> Trigger Condition Matcher -> Quality Filter
          -> Chain Traversal -> Response Generator

Usage:
    python attackchain_advisor.py "I noticed ori and dest params reflected
    into the same inline <script> block, encoded differently"

Requires `ollama serve` running locally.
"""

import json
import os
import sys
import urllib.request
from pathlib import Path

DATA_DIR = Path(__file__).parent / "experimental data" / "experimental data"
KNOWLEDGE_FILE = DATA_DIR / "experiential_knowledge_41.json"
QUALITY_FILE = DATA_DIR / "quality_metrics.json"
XREF_FILE = DATA_DIR / "cross_references.json"

OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5vl:3b")


def load_data():
    knowledge = json.loads(KNOWLEDGE_FILE.read_text(encoding="utf-8"))["knowledge"]
    quality = json.loads(QUALITY_FILE.read_text(encoding="utf-8"))
    xref = json.loads(XREF_FILE.read_text(encoding="utf-8"))
    return knowledge, quality, xref


def build_quality_index(quality):
    """id -> {pass_count, composite-ish summary, failed_checks}"""
    index = {}
    for item in quality["quality_checklist"]["items"]:
        checks = item["checks"]
        failed = [name for name, c in checks.items() if not c["passed"]]
        pass_count = sum(1 for c in checks.values() if c["passed"])
        index[item["id"]] = {
            "pass_count": pass_count,
            "max": len(checks),
            "failed_checks": failed,
        }
    return index


def build_xref_index(xref):
    """id -> list of (target_id, target_title) it points to"""
    out = {}
    for pair in xref["complementary_pairs"]:
        a, b = pair["a"]["id"], pair["b"]["id"]
        out.setdefault(a, []).append((b, pair["b"]["title"]))
    return out


def call_llm(prompt, system=None):
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "system": system or "",
        "stream": False,
    }
    req = urllib.request.Request(
        "http://localhost:11434/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return body["response"]


def match_entry(observation, knowledge):
    """Ask the LLM to pick the single best-matching entry id by trigger_condition."""
    catalogue = "\n".join(
        f"- {k['id']}: {k['title']} | triggers: {', '.join(k['trigger_condition'])}"
        for k in knowledge
    )
    system = (
        "You are a retrieval matcher. Given a researcher's observation and a "
        "catalogue of knowledge-entry trigger conditions, reply with ONLY the "
        "single best-matching entry id (e.g. ek_0040). No explanation."
    )
    prompt = f"Catalogue:\n{catalogue}\n\nObservation:\n{observation}\n\nBest matching id:"
    reply = call_llm(prompt, system=system).strip()
    for k in knowledge:
        if k["id"] in reply:
            return k
    return None


def quality_note(entry_id, quality_index):
    q = quality_index.get(entry_id)
    if not q:
        return "No quality data available."
    if q["pass_count"] == q["max"]:
        return f"High confidence ({q['pass_count']}/{q['max']} quality checks passed)."
    return (
        f"Caveat: only {q['pass_count']}/{q['max']} quality checks passed "
        f"(failed: {', '.join(q['failed_checks'])}). Validate before acting."
    )


def chain_next(entry_id, xref_index, knowledge_by_id):
    nexts = xref_index.get(entry_id, [])
    return [(nid, knowledge_by_id.get(nid, {}).get("title", title)) for nid, title in nexts]


def generate_response(observation, entry, q_note, chain):
    chain_text = (
        "\n".join(f"- {nid}: {title}" for nid, title in chain)
        if chain
        else "No further chained entries found."
    )
    system = (
        "You are AttackChain Advisor, an offensive-security reasoning assistant. "
        "Explain grounded ONLY in the provided entry. Be concise, structured, "
        "and include: what the signal means, the pitfall to watch for, the "
        "confidence/shelf-life, and the next step in the chain."
    )
    prompt = f"""Researcher observation:
{observation}

Matched knowledge entry:
id: {entry['id']}
title: {entry['title']}
category: {entry['category']}
knowledge: {entry['knowledge']}
abstracted_pattern: {entry['abstracted_pattern']['pattern']}
pitfalls: {entry['pitfalls']}
confidence: {entry['confidence']} ({entry['confidence_rationale']})
shelf_life: {entry['shelf_life']}

Quality filter note: {q_note}

Next entries in attack chain:
{chain_text}

Write the advisory response."""
    return call_llm(prompt, system=system)


def run(observation):
    knowledge, quality, xref = load_data()
    knowledge_by_id = {k["id"]: k for k in knowledge}
    quality_index = build_quality_index(quality)
    xref_index = build_xref_index(xref)

    entry = match_entry(observation, knowledge)
    if not entry:
        print("No matching entry found.")
        return

    q_note = quality_note(entry["id"], quality_index)
    chain = chain_next(entry["id"], xref_index, knowledge_by_id)
    response = generate_response(observation, entry, q_note, chain)

    print(f"\n=== Matched: {entry['id']} — {entry['title']} ===\n")
    print(response)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python attackchain_advisor.py "your observation here"')
        sys.exit(1)
    run(" ".join(sys.argv[1:]))
