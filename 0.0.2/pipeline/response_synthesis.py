"""
Response synthesis stage.

Combines the matched-and-ranked knowledge entry with its chain context into
a structured response template, then drives Gemini to turn that
structured data into a readable advisory for the researcher.
"""

import json
import logging
import os
import time
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("response_synthesis")


def build_response_template(top_entry: Dict[str, Any], chain_context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Combine the top-ranked entry and its chain context into one response shape.

    Preserved for backward compatibility.
    """
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


def _call_gemini(prompt: str) -> Optional[str]:
    """
    Make an HTTP POST request to the Gemini API using urllib.

    Returns:
        str | None: The generated response text from Gemini, or None if call fails.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ]
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            candidates = data.get("candidates", [])
            if candidates:
                content = candidates[0].get("content", {})
                parts = content.get("parts", [])
                if parts:
                    return parts[0].get("text")
    except Exception as e:
        logger.warning(f"Error calling Gemini REST API: {e}")

    return None


# ------------------------------------------------------------
# STEP 1: Intent Extraction
# ------------------------------------------------------------

def extract_intent(observation: str) -> str:
    """
    Convert noisy observation into a concise cybersecurity intent using Gemini if available.

    Falls back to original observation if key is missing or call fails.
    """
    logger.info("Extracting intent from observation...")
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.info("No GEMINI_API_KEY environment variable found. Falling back to original observation.")
        return observation

    prompt = (
        "You are a cybersecurity expert. Given a researcher's noisy observation, "
        "rephrase it into a concise, professional, and clear statement of cybersecurity intent / technique being observed. "
        "Respond ONLY with the rephrased intent, nothing else. No preamble, no quotes.\n\n"
        f"Observation: {observation}\n\n"
        "Concise Intent:"
    )
    result = _call_gemini(prompt)
    if result:
        return result.strip()

    logger.warning("Gemini intent extraction failed. Falling back to original observation.")
    return observation


# ------------------------------------------------------------
# STEP 3: Knowledge Consistency Validator
# ------------------------------------------------------------

def validate_consistency(
    retrieval_result: List[Dict[str, Any]],
    ranking_result: List[Dict[str, Any]],
    chain_context: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Validate the consistency across retrieval, ranking, and graph traversal.

    Returns:
        Dict[str, Any]: Validation status block conforming to checked rules.
    """
    issues = []
    checks = {
        "retrieval": False,
        "ranking": False,
        "graph": False,
        "confidence": False
    }

    # 1. Retrieval validation
    if not retrieval_result:
        issues.append("Retrieval result is empty.")
    elif not isinstance(retrieval_result, list):
        issues.append("Retrieval result is not a list.")
    else:
        valid_retrieval = True
        for idx, entry in enumerate(retrieval_result):
            if not isinstance(entry, dict):
                issues.append(f"Retrieval candidate at index {idx} is not a dictionary.")
                valid_retrieval = False
                continue
            entry_id = entry.get("id") or entry.get("entry_id")
            if not entry_id:
                issues.append(f"Retrieval candidate at index {idx} is missing an ID.")
                valid_retrieval = False
        checks["retrieval"] = valid_retrieval

    # 2. Ranking validation
    top_entry = None
    if not ranking_result:
        issues.append("Ranking result is empty.")
    elif not isinstance(ranking_result, list):
        issues.append("Ranking result is not a list.")
    else:
        top_entry = ranking_result[0]
        if not isinstance(top_entry, dict):
            issues.append("Top ranked entry is not a dictionary.")
        else:
            valid_ranking = True
            if "composite_score" not in top_entry:
                issues.append("Top entry is missing 'composite_score'.")
                valid_ranking = False
            if "similarity" not in top_entry and "similarity_score" not in top_entry:
                issues.append("Top entry is missing 'similarity'.")
                valid_ranking = False
            checks["ranking"] = valid_ranking

    # 3. Graph validation
    if not chain_context:
        issues.append("Chain context is missing.")
    elif not isinstance(chain_context, dict):
        issues.append("Chain context is not a dictionary.")
    else:
        valid_graph = True
        attack_chain = chain_context.get("attack_chain", [])
        if not attack_chain:
            issues.append("Attack chain is empty.")
            valid_graph = False

        edges = chain_context.get("edges", [])
        for idx, edge in enumerate(edges):
            if not isinstance(edge, dict):
                issues.append(f"Graph edge at index {idx} is not a dictionary.")
                valid_graph = False
                continue
            if not edge.get("source") or not edge.get("target"):
                issues.append(f"Graph edge at index {idx} has missing source/target: {edge}.")
                valid_graph = False
        checks["graph"] = valid_graph

    # 4. Confidence validation
    if top_entry and isinstance(top_entry, dict):
        confidence = top_entry.get("confidence") or top_entry.get("confidence_tier")
        if not confidence:
            issues.append("Confidence level is missing from the top entry.")
        else:
            checks["confidence"] = True

    passed = len(issues) == 0 and all(checks.values())

    return {
        "passed": passed,
        "checks": checks,
        "issues": issues
    }


# ------------------------------------------------------------
# STEP 4: LLM Explanation & Fallback Response
# ------------------------------------------------------------

def _generate_fallback_response(
    observation: str,
    intent: str,
    top_entry: Dict[str, Any],
    chain_context: Dict[str, Any],
    validation_result: Dict[str, Any]
) -> str:
    """
    Fallback implementation generating the response report using a local template.
    """
    entry_id = top_entry.get("id") or top_entry.get("entry_id", "unknown")
    title = top_entry.get("title", "unknown")
    similarity = top_entry.get("similarity", top_entry.get("similarity_score", "N/A"))
    confidence = top_entry.get("confidence", top_entry.get("confidence_tier", "N/A"))

    pitfalls = top_entry.get("pitfalls", [])
    if isinstance(pitfalls, list):
        pitfalls_str = "\n".join(f"- {p}" for p in pitfalls) if pitfalls else "- None documented"
    else:
        pitfalls_str = f"- {pitfalls}"

    attack_chain = chain_context.get("attack_chain", [])
    chain_nodes = []
    for node in attack_chain:
        nid = node.get("entry_id")
        if node.get("exists_in_quality_dataset"):
            title_node = node.get("title", "unknown")
            chain_nodes.append(f"{nid} ({title_node})")
        else:
            chain_nodes.append(f"{nid} [outside curated set]")
    chain_str = " -> ".join(chain_nodes) if chain_nodes else "No path discovered."

    why_matches = top_entry.get("knowledge", "The observed behavior matches the signature and trigger conditions of the selected entry.")

    recommendation = (
        f"Review the implementation details for {entry_id}. "
        "Validate the presence of the vulnerability using non-disruptive testing, "
        "and apply the appropriate input filtering or access control mitigations as outlined in the pitfalls."
    )

    return f"""### Observation
{observation}

### Intent
{intent}

### Most Relevant Technique
{entry_id} — {title} (Similarity: {similarity})

### Why it Matches
{why_matches}

### Confidence
{confidence}

### Pitfalls
{pitfalls_str}

### Suggested Attack Chain
{chain_str}

### Recommendation
{recommendation}"""


def generate_response(
    observation: str,
    intent: str,
    ranking_result: List[Dict[str, Any]],
    chain_context: Dict[str, Any],
    validation_result: Dict[str, Any]
) -> str:
    """
    Generate an explainable AI response explaining the matched entries and chain context.

    Instructs the LLM to never invent techniques or paths and only explain provided data.
    If Gemini is unavailable, falls back to a formatted Python template.
    """
    if not ranking_result:
        return "No matching techniques could be retrieved for the observation."

    top_entry = ranking_result[0]

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.info("No Gemini API key available. Generating local template explanation.")
        return _generate_fallback_response(observation, intent, top_entry, chain_context, validation_result)

    entry_id = top_entry.get("id") or top_entry.get("entry_id", "unknown")
    title = top_entry.get("title", "unknown")
    similarity = top_entry.get("similarity", top_entry.get("similarity_score", "N/A"))
    confidence = top_entry.get("confidence", top_entry.get("confidence_tier", "N/A"))
    knowledge_text = top_entry.get("knowledge", "")
    abstracted_pattern = top_entry.get("abstracted_pattern", {}).get("pattern", "")
    pitfalls = top_entry.get("pitfalls", [])

    attack_chain = chain_context.get("attack_chain", [])
    chain_list = []
    for node in attack_chain:
        nid = node.get("entry_id")
        if node.get("exists_in_quality_dataset"):
            chain_list.append(f"{nid} ({node.get('title', 'unknown')})")
        else:
            chain_list.append(f"{nid} [outside curated set]")
    chain_str = " -> ".join(chain_list) if chain_list else "None"

    prompt = f"""You are AttackChain Advisor, an advanced offensive-security reasoning engine.
Your task is to explain the provided cybersecurity data concisely and professionally.

CRITICAL RULES:
1. NEVER invent any cybersecurity techniques or attack paths not present in the provided data.
2. ONLY explain the structured information provided below.
3. Keep all reasoning highly precise, technical, and objective.

INPUT DATA:
- Observation: {observation}
- Intent: {intent}
- Most Relevant Technique: {entry_id} — {title} (Similarity: {similarity})
- Knowledge Details: {knowledge_text}
- Abstracted Pattern: {abstracted_pattern}
- Confidence: {confidence}
- Pitfalls: {pitfalls}
- Suggested Attack Chain: {chain_str}
- Validation Result: {validation_result}

Generate a report matching EXACTLY the following structure (markdown headers). Do not add other sections:

### Observation
[Restate or explain the initial observation]

### Intent
[Provide the extracted intent]

### Most Relevant Technique
[Name and ID of the matching technique]

### Why it Matches
[Explain based on the matching conditions and knowledge provided]

### Confidence
[The confidence level and rationale from the data]

### Pitfalls
[The pitfalls to watch for as provided in the input]

### Suggested Attack Chain
[The attack chain path and explain how the transition happens based strictly on the input data]

### Recommendation
[Provide actionable recommendations based strictly on the matched technique and pitfalls]"""

    res = _call_gemini(prompt)
    if res:
        return res.strip()

    logger.warning("Gemini response generation failed. Falling back to local template.")
    return _generate_fallback_response(observation, intent, top_entry, chain_context, validation_result)


# ------------------------------------------------------------
# STEP 5: Public API
# ------------------------------------------------------------

def analyze(observation: str) -> Dict[str, Any]:
    """
    Orchestrates the entire AttackChain Advisor pipeline.

    Runs: Intent Extraction -> Retrieval -> Quality Ranking -> Graph Traversal ->
          Consistency Validation -> LLM Response Generation.

    Args:
        observation (str): The initial researcher observation.

    Returns:
        Dict[str, Any]: Structured dictionary with intermediate results, final answer, and metadata.
    """
    start_time = time.perf_counter()

    # Import upstream modules inside functions to prevent circular dependencies
    from embedding_retrieval import retrieve
    from quality_ranking import rank
    from graph_traversal import get_chain_context

    # 1. Intent Extraction
    intent = extract_intent(observation)

    # 2. Retrieval
    retrieval_result = retrieve(observation)

    # 3. Quality Ranking
    ranking_result = rank(retrieval_result)

    # 4. Graph Traversal
    top_entry = ranking_result[0] if ranking_result else None
    if top_entry:
        entry_id = top_entry.get("id") or top_entry.get("entry_id")
        chain_context = get_chain_context(entry_id)
    else:
        chain_context = {
            "entry_id": "",
            "attack_chain": [],
            "chain_length": 0,
            "graph_depth": 0,
            "reachable_nodes": [],
            "terminal_nodes": [],
            "edges": [],
            "graph_statistics": {"nodes_traversed": 0, "edges_followed": 0},
            "next": [],
            "prev": [],
            "truncated_ids": []
        }

    # 5. Knowledge Consistency Validation
    validation_result = validate_consistency(retrieval_result, ranking_result, chain_context)

    # 6. Response Generation
    api_key = os.environ.get("GEMINI_API_KEY")
    llm_used = api_key is not None
    fallback_used = not llm_used

    answer = ""
    if top_entry:
        try:
            answer = generate_response(observation, intent, ranking_result, chain_context, validation_result)
        except Exception as e:
            logger.error(f"Error in response generation: {e}")
            answer = _generate_fallback_response(observation, intent, top_entry, chain_context, validation_result)
            fallback_used = True
    else:
        answer = "No matching techniques could be retrieved for the observation."

    # Adjust fallback flags based on response outcome
    if llm_used and answer.startswith("### Observation"):
        fallback_used = True
        llm_used = False

    execution_time_ms = int((time.perf_counter() - start_time) * 1000)
    model_used = "gemini-2.5-flash" if llm_used else None

    metadata = {
        "model_used": model_used,
        "llm_used": llm_used,
        "fallback_used": fallback_used,
        "execution_time_ms": execution_time_ms
    }

    return {
        "intent": intent,
        "retrieval": retrieval_result,
        "ranking": ranking_result,
        "graph": chain_context,
        "validation": validation_result,
        "answer": answer,
        "metadata": metadata
    }


def synthesize(observation: str, top_entry: dict, chain_context: dict) -> str:
    """
    Legacy response synthesis function. Preserved for backward compatibility.
    """
    intent = extract_intent(observation)
    validation = validate_consistency([top_entry], [top_entry], chain_context)
    return generate_response(observation, intent, [top_entry], chain_context, validation)
