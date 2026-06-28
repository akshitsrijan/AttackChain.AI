"""
AttackChain Advisor — orchestrator.

Wires the full pipeline together: embedding retrieval -> quality ranking ->
graph traversal -> response synthesis, and exposes it as a CLI.

    python main.py "your observation here"

Requires `ollama serve` or `GEMINI_API_KEY` environment variable.
"""

import json
import logging
import sys

from embedding_retrieval import retrieve
from quality_ranking import rank
from graph_traversal import get_chain_context
from response_synthesis import build_response_template, synthesize, analyze

# Third-party HTTP/model-loading libraries log a HEAD/GET request per file on
# every model load. That's useful when debugging a download problem, but it
# drowns out the pipeline's own output on every normal run, so keep it quiet
# unless something above WARNING actually goes wrong.
for _noisy_logger in ("httpx", "huggingface_hub", "urllib3", "sentence_transformers"):
    logging.getLogger(_noisy_logger).setLevel(logging.WARNING)

def run(observation: str, with_llm: bool = True) -> dict:
    """Run one observation through the full pipeline, returning the structured response."""
    result = analyze(observation)

    ranking = result.get("ranking", [])
    if not ranking:
        return {"error": "No matching entry found."}

    top_entry = ranking[0]
    chain_context = result.get("graph", {})

    response = build_response_template(top_entry, chain_context)
    response["advisory_text"] = result["answer"]

    # Include additional orchestration fields for integration and debugging
    response["intent"] = result["intent"]
    response["retrieval"] = result["retrieval"]
    response["ranking"] = result["ranking"]
    response["graph"] = result["graph"]
    response["validation"] = result["validation"]
    response["answer"] = result["answer"]
    response["metadata"] = result["metadata"]

    return response


_SEP = "=" * 78


def _print_result(observation: str, response: dict) -> None:
    """Print one pipeline result as a readable, labelled block."""
    matched = response.get("matched", {})
    reasoning = response.get("reasoning", {})
    chain_next = [n["id"] for n in response.get("chain", {}).get("next", [])]

    print(_SEP)
    print(f"Observation: {observation}")
    print("-" * 78)
    print(f"  Matched        {matched.get('id', '?')} - {matched.get('title', '?')}")
    print(f"  Confidence     {response.get('confidence', '?')} "
          f"(tier: {reasoning.get('confidence_tier', '?')})")
    print(f"  Similarity     {reasoning.get('similarity_score', '?')}")
    print(f"  Quality note   {reasoning.get('quality_note', '?')}")
    print(f"  Chain next     {chain_next if chain_next else '(none)'}")


if __name__ == "__main__":
    if len(sys.argv) >= 2:
        observation = " ".join(sys.argv[1:])
    else:
        observation = input("Enter a security observation: ").strip()

    if not observation:
        print("No observation entered.")
        sys.exit(0)

    response = run(observation)
    print()
    _print_result(observation, response)
    print(_SEP)
    print("Advisory:\n")
    print(response.get("advisory_text", json.dumps(response, indent=2)))
    print(_SEP)
