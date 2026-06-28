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
import logging
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

import networkx as nx

# Configure logging at INFO level
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("graph_traversal")

# Resolve directories and files
DATA_DIR = Path(__file__).parent.parent / "experimental data" / "experimental data"
XREF_FILE = DATA_DIR / "cross_references.json"
KNOWLEDGE_FILE = DATA_DIR / "experiential_knowledge_41.json"

# Load JSON datasets at module import
_XREF = json.loads(XREF_FILE.read_text(encoding="utf-8"))
_KNOWLEDGE = json.loads(KNOWLEDGE_FILE.read_text(encoding="utf-8"))["knowledge"]

# ------------------------------------------------------------
# STEP 1: Load graph and KNOWLEDGE_INDEX
# ------------------------------------------------------------

# 1. GRAPH: responsible ONLY for topology (nodes and directed edges).
# No knowledge metadata is stored in GRAPH.
GRAPH = nx.DiGraph()

# Populate GRAPH topology
for _pair in _XREF["complementary_pairs"]:
    a_id = _pair["a"]["id"]
    b_id = _pair["b"]["id"]
    GRAPH.add_node(a_id)
    GRAPH.add_node(b_id)
    GRAPH.add_edge(a_id, b_id)

# 2. KNOWLEDGE_INDEX: independent dictionary for O(1) metadata lookup
KNOWLEDGE_INDEX: Dict[str, Dict[str, Any]] = {}
for entry in _KNOWLEDGE:
    KNOWLEDGE_INDEX[entry["id"]] = entry

# Set of curated IDs in the quality dataset
CURATED_IDS: Set[str] = set(KNOWLEDGE_INDEX.keys())

# NODE_INDEX for O(1) lookup of node presence / compatibility
NODE_INDEX: Dict[str, Dict[str, Any]] = KNOWLEDGE_INDEX


def make_node_representation(node_id: str) -> Dict[str, Any]:
    """
    Generate a node representation object.

    If the node exists in the quality-assessed dataset, returns its full metadata.
    Otherwise, returns a lightweight placeholder for out-of-range handling.

    Args:
        node_id (str): The ID of the node to look up.

    Returns:
        Dict[str, Any]: A dictionary representing the node.
    """
    if node_id in KNOWLEDGE_INDEX:
        entry = KNOWLEDGE_INDEX[node_id]
        return {
            "entry_id": node_id,
            "title": entry.get("title", "unknown"),
            "category": entry.get("category", "unknown"),
            "exists_in_quality_dataset": True,
        }
    else:
        return {
            "entry_id": node_id,
            "exists_in_quality_dataset": False,
        }


def _node_info_legacy(node_id: str) -> Dict[str, Any]:
    """
    Generate a legacy node representation dictionary for backward compatibility.

    Args:
        node_id (str): The ID of the node to look up.

    Returns:
        Dict[str, Any]: Legacy dictionary schema expected by upstream/downstream modules.
    """
    if node_id in KNOWLEDGE_INDEX:
        entry = KNOWLEDGE_INDEX[node_id]
        return {
            "id": node_id,
            "title": entry.get("title", "unknown"),
            "category": entry.get("category", "unknown"),
        }
    else:
        return {
            "id": node_id,
            "title": "[outside curated set]",
            "category": "unknown",
        }


# ------------------------------------------------------------
# STEP 2 & 3: Traversal logic
# ------------------------------------------------------------

def _traverse_internal(entry_id: str, depth: int = 2) -> Tuple[List[str], List[Dict[str, str]]]:
    """
    Iterative queue-based BFS to traverse outgoing edges up to a maximum depth.

    Avoids infinite loops by tracking visited nodes. Also tracks edges followed.

    Args:
        entry_id (str): Starting entry ID.
        depth (int): Max hop depth to traverse.

    Returns:
        Tuple[List[str], List[Dict[str, str]]]:
            Ordered list of visited node IDs, and list of edges followed in {"source", "target"} format.
    """
    if not entry_id:
        return [], []

    visited: Set[str] = set()
    discovered: Set[str] = {entry_id}
    ordered_path: List[str] = []
    edges: List[Dict[str, str]] = []

    # Queue contains tuples of (node_id, current_depth)
    queue: deque = deque([(entry_id, 0)])

    while queue:
        node, current_depth = queue.popleft()

        if node in visited:
            continue

        visited.add(node)
        ordered_path.append(node)

        # Do not traverse beyond the maximum depth
        if current_depth < depth:
            successors = sorted(GRAPH.successors(node)) if node in GRAPH else []
            for succ in successors:
                if succ not in discovered:
                    discovered.add(succ)
                    queue.append((succ, current_depth + 1))
                    edges.append({
                        "source": node,
                        "target": succ,
                    })

    return ordered_path, edges


def traverse(entry_id: str, depth: int = 2) -> List[Dict[str, Any]]:
    """
    Walk up to `depth` hops forward from an entry using BFS, returning ordered node objects.

    Never revisits a node, avoids loops.

    Args:
        entry_id (str): Starting entry ID.
        depth (int): Max depth to traverse.

    Returns:
        List[Dict[str, Any]]: Ordered path of node representations.
    """
    path_ids, _ = _traverse_internal(entry_id, depth)
    return [make_node_representation(node_id) for node_id in path_ids]


# ------------------------------------------------------------
# STEP 4: Suggested chains
# ------------------------------------------------------------

def suggested_chains(entry_id: str, depth: int = 2) -> Dict[str, Any]:
    """
    Build suggested attack chain dictionary with start node, depth, nodes, and edges.

    Args:
        entry_id (str): The starting entry ID.
        depth (int): The maximum traversal depth.

    Returns:
        Dict[str, Any]: The suggested chain dictionary structure.
    """
    path_ids, edges = _traverse_internal(entry_id, depth)
    nodes = [make_node_representation(node_id) for node_id in path_ids]
    return {
        "start": entry_id,
        "depth": depth,
        "nodes": nodes,
        "edges": edges,
        "chain_length": len(nodes),
    }


# ------------------------------------------------------------
# STEP 6: Public API with backward compatibility fallback
# ------------------------------------------------------------

def get_chain_context(entry_id: str) -> Dict[str, Any]:
    """
    Exposes full chain context for Person D, while maintaining backward compatibility.

    Args:
        entry_id (str): Starting node of the traversal.

    Returns:
        Dict[str, Any]: Context containing new Person D API fields and legacy fields.
    """
    # 1. Execute traversal and calculate new API fields (default depth=2)
    depth = 2
    path_ids, edges = _traverse_internal(entry_id, depth)
    attack_chain = [make_node_representation(node_id) for node_id in path_ids]

    terminal_nodes = []
    for node_id in path_ids:
        successors = list(GRAPH.successors(node_id)) if node_id in GRAPH else []
        if not successors:
            terminal_nodes.append(make_node_representation(node_id))

    graph_stats = {
        "nodes_traversed": len(attack_chain),
        "edges_followed": len(edges),
    }

    # 2. Compute legacy next/prev fields for backward compatibility (depth=2)
    next_ids: Set[str] = set()
    prev_ids: Set[str] = set()

    # Forward legacy lookups (successors up to depth 2)
    frontier = {entry_id}
    for _ in range(depth):
        new_frontier = set()
        for node in frontier:
            new_frontier |= set(GRAPH.successors(node)) if node in GRAPH else set()
        next_ids |= new_frontier
        frontier = new_frontier

    # Backward legacy lookups (predecessors up to depth 2)
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

    legacy_next = [_node_info_legacy(n) for n in sorted(next_ids)]
    legacy_prev = [_node_info_legacy(n) for n in sorted(prev_ids)]

    return {
        # Person D API
        "entry_id": entry_id,
        "attack_chain": attack_chain,
        "chain_length": len(attack_chain),
        "graph_depth": depth,
        "reachable_nodes": attack_chain,
        "terminal_nodes": terminal_nodes,
        "edges": edges,
        "graph_statistics": graph_stats,

        # Downstream Legacy API Compatibility Fields
        "next": legacy_next,
        "prev": legacy_prev,
        "truncated_ids": truncated,
    }


# ------------------------------------------------------------
# STEP 5: Testing
# ------------------------------------------------------------

def _test_known_pairs() -> None:
    """
    Verify known complementary relationship paths. Prints PASS or FAIL.
    """
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
    print("ek_0002 chain context:")
    print(json.dumps(get_chain_context("ek_0002"), indent=2))
