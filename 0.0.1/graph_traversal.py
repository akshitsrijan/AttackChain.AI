"""
Graph traversal stage.

Builds a directed graph of complementary knowledge entries and traverses it
from a matched entry to surface the attack chain it belongs to: what it
typically leads to (next steps) and what typically precedes it (prior
steps). The underlying graph extends beyond the curated, quality-assessed
entry set, so any traversal that lands outside that curated set is flagged
rather than silently dropped.
"""

import json
from pathlib import Path

import networkx as nx

DATA_DIR = Path(__file__).parent.parent / "experimental data" / "experimental data"
XREF_FILE = DATA_DIR / "cross_references.json"
KNOWLEDGE_FILE = DATA_DIR / "experiential_knowledge_41.json"

_XREF = json.loads(XREF_FILE.read_text(encoding="utf-8"))
_KNOWLEDGE = json.loads(KNOWLEDGE_FILE.read_text(encoding="utf-8"))["knowledge"]
CURATED_IDS = {k["id"] for k in _KNOWLEDGE}

# Build the directed graph from complementary pairs (a -> b). Traversal walks
# this graph in both directions to recover predecessors as well as successors.
GRAPH = nx.DiGraph()
for _pair in _XREF["complementary_pairs"]:
    a, b = _pair["a"], _pair["b"]
    GRAPH.add_node(a["id"], title=a["title"], category=a["category"])
    GRAPH.add_node(b["id"], title=b["title"], category=b["category"])
    GRAPH.add_edge(a["id"], b["id"])


def _node_info(node_id: str) -> dict:
    data = GRAPH.nodes[node_id]
    return {"id": node_id, "title": data.get("title", "[outside curated set]"), "category": data.get("category", "unknown")}


def traverse(entry_id: str, depth: int = 2) -> dict:
    """Walk up to `depth` hops forward and backward from an entry, flagging out-of-range IDs."""
    next_ids = set()
    prev_ids = set()

    frontier = {entry_id}
    for _ in range(depth):
        new_frontier = set()
        for node in frontier:
            new_frontier |= set(GRAPH.successors(node)) if node in GRAPH else set()
        next_ids |= new_frontier
        frontier = new_frontier

    frontier = {entry_id}
    for _ in range(depth):
        new_frontier = set()
        for node in frontier:
            new_frontier |= set(GRAPH.predecessors(node)) if node in GRAPH else set()
        prev_ids |= new_frontier
        frontier = new_frontier

    next_ids.discard(entry_id)
    prev_ids.discard(entry_id)

    truncated = sorted((next_ids | prev_ids) - CURATED_IDS)

    return {
        "next": [_node_info(n) for n in sorted(next_ids)],
        "prev": [_node_info(p) for p in sorted(prev_ids)],
        "truncated_ids": truncated,
    }


def get_chain_context(entry_id: str) -> dict:
    """Public entry point: full chain context (next/prev/truncated) for a matched entry."""
    if entry_id not in GRAPH:
        return {"next": [], "prev": [], "truncated_ids": []}
    return traverse(entry_id, depth=2)


def _test_known_pairs() -> None:
    """Sanity check: known complementary pairs should appear as direct chain links."""
    cases = [
        ("ek_0002", "ek_0003"),
        ("ek_0012", "ek_0014"),
        ("ek_0013", "ek_0014"),
    ]
    for source, expected_next in cases:
        chain = get_chain_context(source)
        next_ids = [n["id"] for n in chain["next"]]
        status = "PASS" if expected_next in next_ids else "FAIL"
        print(f"{status}: {source} -> expected {expected_next} in next {next_ids}")


if __name__ == "__main__":
    _test_known_pairs()
    print()
    print("ek_0002 chain context:", json.dumps(get_chain_context("ek_0002"), indent=2))
