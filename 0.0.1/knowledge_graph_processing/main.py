"""
AttackChain Advisor — orchestrator.

Wires the full pipeline together: embedding retrieval -> quality ranking ->
graph traversal -> response synthesis, and exposes it as a CLI.

    python main.py "your observation here"

Requires `ollama serve` running locally for the synthesis stage.
"""

import json
import sys

from embedding_retrieval import retrieve
from quality_ranking import rank
from graph_traversal import get_chain_context
from response_synthesis import build_response_template, synthesize

# Example observations used to exercise the full pipeline end to end.
DEMO_OBSERVATIONS = [
    "I'm proxying requests through gopher and noticed CRLF sequences are tolerated "
    "inside the gopher URI without rejection",
    "curl followed a redirect from a proxied connection to a direct connection and "
    "the Proxy-Authorization header was still attached",
    "I see different header validation outcomes for the same payload depending on "
    "whether the request arrived over HTTP/1.1 or HTTP/2",
    "the ori and dest URL parameters are reflected into the same inline script block "
    "but one encodes double quotes as %22 and the other as a literal backslash quote",
    "a redirect target resolves to a host that falls outside the configured proxy scope",
]


def run(observation: str, with_llm: bool = True) -> dict:
    """Run one observation through the full pipeline, returning the structured response."""
    candidates = retrieve(observation)
    if not candidates:
        return {"error": "No matching entry found."}

    ranked = rank(candidates)
    top_entry = ranked[0]
    chain_context = get_chain_context(top_entry["id"])

    response = build_response_template(top_entry, chain_context)

    if with_llm:
        try:
            response["advisory_text"] = synthesize(observation, top_entry, chain_context)
        except Exception as exc:
            response["advisory_text"] = f"(LLM synthesis unavailable: {exc})"

    return response


def _run_demo_examples() -> None:
    """Exercise the full pipeline against a handful of representative observations."""
    for observation in DEMO_OBSERVATIONS:
        response = run(observation, with_llm=False)
        matched = response.get("matched", {})
        print(f"observation: {observation[:70]}...")
        print(f"  -> matched {matched.get('id')}: {matched.get('title')}")
        print(f"     confidence_tier={response['reasoning']['confidence_tier']}")
        print(f"     chain_next={[n['id'] for n in response['chain']['next']]}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        _run_demo_examples()
        sys.exit(0)

    observation = " ".join(sys.argv[1:])
    response = run(observation)
    matched = response.get("matched", {})
    print(f"\n=== Matched: {matched.get('id')} — {matched.get('title')} ===\n")
    print(response.get("advisory_text", json.dumps(response, indent=2)))
