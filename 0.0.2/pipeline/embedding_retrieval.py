"""
Embedding retrieval stage - transformer-based semantic search.

Converts each knowledge entry into a dense sentence embedding using the
``sentence-transformers/all-MiniLM-L6-v2`` model, then matches a researcher's
free-text observation against that embedding space to find the most relevant
entries.

The public contract ``retrieve(observation) -> list[dict]`` is unchanged, so
all downstream stages (quality_ranking, graph_traversal, response_synthesis)
continue to work without modification.

Corpus embeddings are cached to disk as a ``.npz`` file and are regenerated
only when the dataset changes (detected via an MD5 fingerprint of entry IDs).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from pathlib import Path
from typing import List, Tuple

import numpy as np
from sentence_transformers import SentenceTransformer

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configurable weights and scoring parameters
# ---------------------------------------------------------------------------

EMBEDDING_WEIGHT: float = 0.75
KEYWORD_WEIGHT: float = 0.25
ENTITY_BONUS: float = 0.02
MAX_ENTITY_BONUS: float = 0.08
EXACT_PHRASE_BONUS: float = 0.05
DOMAIN_MATCH_BONUS: float = 0.08
DOMAIN_MISMATCH_PENALTY: float = 0.10
CATEGORY_MATCH_BONUS: float = 0.05
TECHNIQUE_MATCH_BONUS: float = 0.05

CANDIDATE_POOL_SIZE: int = 20
MIN_MATCHING_CANDIDATES: int = min(5, CANDIDATE_POOL_SIZE)

FIELD_WEIGHTS: dict[str, float] = {
    "title": 3.0,
    "technique": 3.0,
    "tags": 2.0,
    "summary": 2.0,
    "recommendations": 1.0,
    "pitfalls": 1.0,
    "category": 1.0,
}

MINIMAL_STOP_WORDS: set[str] = {
    "a", "an", "the", "and", "or", "but", "is", "are", "was", "were", 
    "of", "to", "for", "in", "on", "at", "by", "with", "from", "it", 
    "its", "this", "that", "these", "those"
}

SYNONYM_GROUPS: list[dict] = [
    {
        "triggers": ["credential dumping", "credential theft", "lsass", "secretsdump", "mimikatz"],
        "expansions": ["credential dumping", "credential theft", "lsass", "secretsdump", "mimikatz"][:6]
    },
    {
        "triggers": ["powershell", "script execution", "shell"],
        "expansions": ["powershell", "script execution", "shell"][:6]
    },
    {
        "triggers": ["rdp", "remote desktop", "remote desktop protocol", "remote access"],
        "expansions": ["rdp", "remote desktop", "remote desktop protocol", "remote access"][:6]
    },
    {
        "triggers": ["phishing", "malicious email", "social engineering"],
        "expansions": ["phishing", "malicious email", "social engineering"][:6]
    },
    {
        "triggers": ["lateral movement", "pivot", "remote execution"],
        "expansions": ["lateral movement", "pivot", "remote execution"][:6]
    },
    {
        "triggers": ["malware", "trojan", "payload"],
        "expansions": ["malware", "trojan", "payload"][:6]
    }
]

ENTITY_TERMS: list[str] = [
    "powershell",
    "rdp",
    "smb",
    "lsass",
    "kerberos",
    "ntlm",
    "mimikatz",
    "psexec",
    "ssh",
    "vpn",
    "outlook",
    "exchange",
    "encodedcommand",
    "sql injection",
    "xss",
    "csrf",
    "phishing",
]

CVE_PATTERN = re.compile(r"\bcve-\d{4}-\d{4,}\b", re.IGNORECASE)
MITRE_PATTERN = re.compile(r"\b(?:t\d{4}(?:\.\d{3})?|ta\d{4}|s\d{4}|g\d{4}|m\d{4})\b", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Cybersecurity Domain Keyword Rules
# ---------------------------------------------------------------------------

DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "EMAIL_ATTACK": ["email", "mail", "attachment", "phishing", "outlook", "smtp", "spoofing", "malicious email"],
    "WEB_ATTACK": ["xss", "csrf", "cookie", "dom", "javascript", "session", "browser", "http", "cors", "web", "sql injection", "sqli", "cross-site", "scripting", "ssrf"],
    "CREDENTIAL_ACCESS": ["credential", "password", "hash", "lsass", "ntlm", "kerberos", "mimikatz", "secretsdump", "golden ticket", "pass-the-hash", "sam", "vault", "keychain"],
    "EXECUTION": ["powershell", "cmd", "shell", "script", "command", "terminal", "bash", "wmic", "execution", "run", "psexec"],
    "REMOTE_ACCESS": ["rdp", "ssh", "vpn", "remote desktop", "telnet", "vnc"],
    "LATERAL_MOVEMENT": ["smb", "psexec", "wmic", "pivot", "lateral", "movement"],
    "PRIVILEGE_ESCALATION": ["escalation", "privilege", "uac", "sudo", "root", "system", "bypass"],
    "MALWARE": ["malware", "trojan", "payload", "virus", "worm", "backdoor", "spyware", "ransomware", "loader", "dropper", "implant", "rootkit", "dll sideloading", "sideloading"],
    "NETWORK": ["network", "dns", "ip", "port", "scan", "sniff", "spoof", "proxy", "gopher", "ssrf"],
    "AUTHENTICATION": ["mfa", "auth", "login", "token", "session", "bypass", "authorization", "ntlm relay", "relay"],
    "DISCOVERY": ["discovery", "recon", "scan", "enumeration", "enum", "active directory", "domain controller", "ad"],
    "PERSISTENCE": ["persistence", "registry", "scheduled task", "cron", "startup", "autorun", "service"],
    "COLLECTION": ["collection", "harvest", "gather", "grab"],
    "EXFILTRATION": ["exfiltration", "leak", "exfiltrate", "steal", "send"]
}

MITRE_TO_DOMAIN: dict[str, str] = {
    "t1059": "EXECUTION",
    "t1003": "CREDENTIAL_ACCESS",
    "t1021": "LATERAL_MOVEMENT",
    "t1078": "PRIVILEGE_ESCALATION",
    "t1543": "PERSISTENCE",
    "t1047": "EXECUTION",
    "t1133": "REMOTE_ACCESS",
    "t1566": "EMAIL_ATTACK",
}

# ---------------------------------------------------------------------------
# Preprocessing and Query Enhancement Helpers
# ---------------------------------------------------------------------------

def normalize_only(text: str) -> str:
    """Lowercase, strip word-boundary punctuation, and normalize whitespace."""
    if not text:
        return ""
    text = text.lower()
    strip_chars = '.,;:?!()[]{}""\'`~*<>^'
    tokens = text.split()
    cleaned = []
    for token in tokens:
        clean = token.strip(strip_chars)
        if clean:
            cleaned.append(clean)
    return " ".join(cleaned)


def expand_abbreviations(text: str) -> str:
    """Expand common cybersecurity abbreviations using whole-word matches."""
    abbreviations = {
        "rdp": "remote desktop protocol",
        "smb": "server message block",
        "ad": "active directory",
        "lsass": "local security authority subsystem service",
        "c2": "command and control",
        "mfa": "multi-factor authentication",
        "vpn": "virtual private network",
        "av": "antivirus",
    }
    for abbr, expansion in abbreviations.items():
        text = re.sub(r"\b" + re.escape(abbr) + r"\b", expansion, text)
    return text


def expand_synonym_groups(text: str) -> str:
    """Trigger synonym expansion on both short and long forms, capped at 6 terms."""
    expanded_tokens = list(text.split())
    for group in SYNONYM_GROUPS:
        matched = False
        for trigger in group["triggers"]:
            pattern = r"\b" + re.escape(trigger.lower()) + r"\b"
            if re.search(pattern, text):
                matched = True
                break
        if matched:
            added = 0
            for exp in group["expansions"]:
                if exp.lower() not in text:
                    expanded_tokens.append(exp.lower())
                    added += 1
                    if added >= 6:
                        break
    return " ".join(expanded_tokens)


def normalize_query(query: str) -> str:
    """Normalize query text: lowercase, remove punctuation, expand abbreviations."""
    return expand_abbreviations(normalize_only(query))


def get_embedding_query(query: str) -> str:
    """Pipeline for query embedding: normalize -> expand abbreviations -> expand synonyms."""
    normalized = normalize_query(query)
    return expand_synonym_groups(normalized)


# ---------------------------------------------------------------------------
# Score Calculation Helpers
# ---------------------------------------------------------------------------

def _extract_entities(text: str) -> set[str]:
    """Extract cybersecurity entities case-insensitively (CVEs, MITRE IDs, terms)."""
    entities = set()
    lowered = text.lower()
    for term in ENTITY_TERMS:
        pattern = r"\b" + re.escape(term) + r"\b"
        if re.search(pattern, lowered):
            entities.add(term)
            
    for cve in CVE_PATTERN.findall(lowered):
        entities.add(cve.lower())
        
    for mitre in MITRE_PATTERN.findall(lowered):
        entities.add(mitre.lower())
        
    return entities


def classify_domains(text: str) -> dict:
    """Classify text into domains with a confidence score based on keywords and MITRE IDs.

    Returns
    -------
    dict
        {"domains": set[str], "confidence": float}
    """
    inferred = set()
    lowered = text.lower()
    
    # 1. Map MITRE ID entities to domains (high confidence seed match)
    entities = _extract_entities(text)
    has_mitre_match = False
    for ent in entities:
        base_mitre = ent.split(".")[0]
        if base_mitre in MITRE_TO_DOMAIN:
            inferred.add(MITRE_TO_DOMAIN[base_mitre])
            has_mitre_match = True
            
    # 2. Extract standard domain keywords (hierarchical matched)
    keyword_matches_count = 0
    for domain, keywords in DOMAIN_KEYWORDS.items():
        for kw in keywords:
            pattern = r"\b" + re.escape(kw) + r"\b"
            if re.search(pattern, lowered):
                inferred.add(domain)
                keyword_matches_count += 1
                break # only count one match per domain
                
    if not inferred:
        return {"domains": set(), "confidence": 0.0}
        
    # Determine confidence:
    if has_mitre_match:
        confidence = 1.0
    else:
        # Confidence increases with density of unique matching domains
        confidence = min(0.9, 0.5 + 0.1 * keyword_matches_count)
        
    return {"domains": inferred, "confidence": round(confidence, 2)}


def is_contiguous_sublist(sublist: list[str], full_list: list[str]) -> bool:
    """Check if sublist is a contiguous sequence in full_list (min 2 tokens)."""
    if len(sublist) < 2:
        return False
    n = len(sublist)
    m = len(full_list)
    if n > m:
        return False
    for i in range(m - n + 1):
        if full_list[i : i + n] == sublist:
            return True
    return False


def is_exact_phrase_match(query_tokens: list[str], candidate_tokens: list[str]) -> bool:
    """Check if query is an exact contiguous token-sequence match in candidate."""
    return is_contiguous_sublist(query_tokens, candidate_tokens)


def compute_weighted_keyword_overlap(query_tokens: set[str], candidate_field_tokens: dict[str, set[str]]) -> float:
    """Compute weighted keyword overlap score normalized between 0.0 and 1.0."""
    if not query_tokens:
        return 0.0
    
    total_score = 0.0
    max_field_weight = max(FIELD_WEIGHTS.values())
    
    for token in query_tokens:
        token_max_weight = 0.0
        for field, tokens in candidate_field_tokens.items():
            if token in tokens:
                weight = FIELD_WEIGHTS.get(field, 1.0)
                if weight > token_max_weight:
                    token_max_weight = weight
        total_score += token_max_weight
        
    return total_score / (len(query_tokens) * max_field_weight)


def check_category_alignment(candidate_category: str, query_domains: set[str]) -> bool:
    """Normalize category and check token overlaps against the query domain keywords."""
    normalized_cat = candidate_category.replace("_", " ").replace("-", " ").lower()
    cat_tokens = set(normalized_cat.split())
    
    for dom in query_domains:
        keywords = DOMAIN_KEYWORDS.get(dom, [])
        dom_tokens = set()
        for kw in keywords:
            dom_tokens.update(kw.lower().split())
        if cat_tokens.intersection(dom_tokens):
            return True
    return False


# ---------------------------------------------------------------------------
# Paths and constants
# ---------------------------------------------------------------------------

DATA_DIR: Path = (
    Path(__file__).parent.parent / "experimental data" / "experimental data"
)
KNOWLEDGE_FILE: Path = DATA_DIR / "experiential_knowledge_41.json"
CACHE_FILE: Path = Path(__file__).parent / ".cache_corpus_embeddings.npz"
MODEL_NAME: str = "sentence-transformers/all-MiniLM-L6-v2"

# ---------------------------------------------------------------------------
# Knowledge base - loaded once at module import
# ---------------------------------------------------------------------------

KNOWLEDGE: List[dict] = json.loads(
    KNOWLEDGE_FILE.read_text(encoding="utf-8")
)["knowledge"]
KNOWLEDGE_BY_ID: dict = {entry["id"]: entry for entry in KNOWLEDGE}

# ---------------------------------------------------------------------------
# Startup precomputation and caching (in-memory, no dataset mutation)
# ---------------------------------------------------------------------------

CANDIDATE_TEXTS: dict[str, str] = {}
CANDIDATE_TOKENS: dict[str, dict[str, set[str]]] = {}
CANDIDATE_TOKEN_LISTS: dict[str, list[str]] = {}
CANDIDATE_DOMAINS: dict[str, dict] = {}

def _precompute_candidates():
    global CANDIDATE_TEXTS, CANDIDATE_TOKENS, CANDIDATE_TOKEN_LISTS, CANDIDATE_DOMAINS
    for entry in KNOWLEDGE:
        entry_id = entry["id"]
        
        all_text_parts = []
        for key, val in entry.items():
            if not val:
                continue
            if key in ["id", "source_id", "extracted_at", "confidence_rationale", "shelf_life"]:
                continue
            if isinstance(val, str):
                all_text_parts.append(val)
            elif isinstance(val, list):
                all_text_parts.extend(str(item) for item in val)
            elif isinstance(val, dict):
                for subval in val.values():
                    if isinstance(subval, str):
                        all_text_parts.append(subval)
                    elif isinstance(subval, list):
                        all_text_parts.extend(str(item) for item in subval)
                        
        combined_text = " ".join(all_text_parts)
        normalized_combined = normalize_only(combined_text)
        CANDIDATE_TOKEN_LISTS[entry_id] = normalized_combined.split()
        CANDIDATE_TEXTS[entry_id] = normalized_combined
        
        # Determine candidate domains deterministically
        CANDIDATE_DOMAINS[entry_id] = classify_domains(combined_text)
        
        field_tokens = {}
        for field in ["title", "summary", "technique", "category", "tags", "recommendations", "pitfalls"]:
            val = entry.get(field)
            if not val:
                continue
            if isinstance(val, list):
                text_val = " ".join(str(item) for item in val)
            elif isinstance(val, dict):
                text_val = " ".join(str(v) for v in val.values())
            else:
                text_val = str(val)
                
            norm_field = normalize_only(text_val)
            tokens = {t for t in norm_field.split() if t not in MINIMAL_STOP_WORDS}
            if tokens:
                field_tokens[field] = tokens
        CANDIDATE_TOKENS[entry_id] = field_tokens

# Run precomputation
_precompute_candidates()


# ---------------------------------------------------------------------------
# Model singleton
# ---------------------------------------------------------------------------

_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    """Return the shared SentenceTransformer instance, loading it on first call.

    The model is initialised lazily so that a warm-cache startup incurs
    zero model-load overhead.
    """
    global _model
    if _model is None:
        logger.info("Loading SentenceTransformer model: %s", MODEL_NAME)
        _model = SentenceTransformer(MODEL_NAME)
        logger.info("Model loaded successfully.")
    return _model


# ---------------------------------------------------------------------------
# Corpus document construction
# ---------------------------------------------------------------------------


def _build_document(entry: dict) -> str:
    """Build the single combined text document used to embed a knowledge entry.

    Concatenates the following fields (when present):
    - title
    - category
    - trigger_condition  (list items joined with a space, or raw string)
    - knowledge
    - abstracted_pattern.pattern  (the IF/THEN pattern, if present)

    Parameters
    ----------
    entry : dict
        A single knowledge entry from the corpus.

    Returns
    -------
    str
        A single space-joined string ready for encoding.
    """
    parts: List[str] = []

    title = entry.get("title", "")
    if title:
        parts.append(title)

    category = entry.get("category", "")
    if category:
        parts.append(category)

    trigger_conditions = entry.get("trigger_condition", [])
    if isinstance(trigger_conditions, list):
        parts.append(" ".join(trigger_conditions))
    elif isinstance(trigger_conditions, str) and trigger_conditions:
        parts.append(trigger_conditions)

    knowledge = entry.get("knowledge", "")
    if knowledge:
        parts.append(knowledge)

    abstracted = entry.get("abstracted_pattern", {})
    if isinstance(abstracted, dict):
        pattern = abstracted.get("pattern", "")
        if pattern:
            parts.append(pattern)

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------


def _corpus_fingerprint() -> str:
    """Return an MD5 hex digest that uniquely identifies the current corpus.

    The digest is computed over the ordered list of entry IDs so that any
    addition, removal, or reordering of entries invalidates the cache.

    Returns
    -------
    str
        32-character lowercase hex string.
    """
    ids = [entry["id"] for entry in KNOWLEDGE]
    return hashlib.md5(json.dumps(ids).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Public reusable functions
# ---------------------------------------------------------------------------


def build_corpus_embeddings() -> np.ndarray:
    """Build and return dense embeddings for every entry in the knowledge corpus.

    The result is cached to ``CACHE_FILE`` as a compressed ``.npz`` archive.
    The cache is reloaded automatically when the corpus fingerprint matches.
    The cache is rebuilt when the fingerprint does not match (dataset changed)
    or when the cache file is missing or corrupt.

    Returns
    -------
    np.ndarray
        Shape ``(N, D)`` float32 array.  N = number of knowledge entries,
        D = model embedding dimension (384 for all-MiniLM-L6-v2).
        Every row is L2-normalised so that dot-product equals cosine similarity.
    """
    fingerprint = _corpus_fingerprint()

    # --- attempt cache load ---
    if CACHE_FILE.exists():
        try:
            cached = np.load(str(CACHE_FILE), allow_pickle=False)
            cached_fp = str(cached["fingerprint"])
            if cached_fp == fingerprint:
                logger.info(
                    "Cache hit - loading corpus embeddings from %s", CACHE_FILE
                )
                return cached["embeddings"].astype(np.float32)
            logger.info(
                "Cache fingerprint mismatch - rebuilding corpus embeddings."
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to read cache (%s); rebuilding.", exc)

    # --- generate embeddings ---
    logger.info(
        "Generating embeddings for %d knowledge entries with model '%s'.",
        len(KNOWLEDGE),
        MODEL_NAME,
    )
    t0 = time.perf_counter()
    documents = [_build_document(entry) for entry in KNOWLEDGE]
    model = _get_model()
    embeddings: np.ndarray = model.encode(
        documents,
        convert_to_numpy=True,
        normalize_embeddings=True,  # L2-normalise: dot-product == cosine similarity
        show_progress_bar=False,
    ).astype(np.float32)
    elapsed = time.perf_counter() - t0
    logger.info(
        "Embedding generation complete: %d vectors in %.2f s.",
        len(embeddings),
        elapsed,
    )

    # --- write cache ---
    np.savez_compressed(
        str(CACHE_FILE),
        embeddings=embeddings,
        fingerprint=np.array(fingerprint),
        ids=np.array([entry["id"] for entry in KNOWLEDGE]),
    )
    logger.info("Corpus embeddings cached to %s", CACHE_FILE)

    return embeddings


def embed_query(query: str) -> np.ndarray:
    """Encode a single researcher query into the same embedding space as the corpus.

    Parameters
    ----------
    query : str
        Free-text observation string from the researcher.

    Returns
    -------
    np.ndarray
        Shape ``(D,)`` L2-normalised float32 embedding vector.
    """
    processed = get_embedding_query(query)
    logger.info("Embedding query (processed): %.80s", processed)
    model = _get_model()
    vec: np.ndarray = model.encode(
        processed,
        convert_to_numpy=True,
        normalize_embeddings=True,
    ).astype(np.float32)
    return vec


def top_k_similar(
    query_embedding: np.ndarray,
    corpus_embeddings: np.ndarray,
    k: int = 5,
) -> List[Tuple[str, float]]:
    """Return the top-k corpus entries most similar to the query by cosine similarity.

    Because both the query vector and every corpus row are L2-normalised,
    cosine similarity is computed as a plain matrix-vector dot product.

    Parameters
    ----------
    query_embedding : np.ndarray
        Shape ``(D,)`` query vector (L2-normalised).
    corpus_embeddings : np.ndarray
        Shape ``(N, D)`` corpus matrix (each row L2-normalised).
    k : int
        Number of results to return (default 5).

    Returns
    -------
    List[Tuple[str, float]]
        List of ``(entry_id, similarity_score)`` tuples sorted in descending
        order of similarity.
    """
    sims: np.ndarray = corpus_embeddings @ query_embedding  # shape (N,)
    top_indices = np.argsort(-sims)[:k]
    ids = [entry["id"] for entry in KNOWLEDGE]
    return [(ids[i], float(sims[i])) for i in top_indices]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def retrieve(observation: str, k: int = 3, debug: bool = False) -> List[dict]:
    """Return the top-k candidate knowledge entries for the given observation.

    This is the primary entry point consumed by ``quality_ranking.rank()``.
    Each returned dict is a copy of the original knowledge-entry dict with an
    additional ``"similarity"`` key (float, rounded to 4 decimal places).

    Parameters
    ----------
    observation : str
        Free-text security observation from the researcher.
    k : int
        Number of candidates to return.  Defaults to 3 to match the contract
        expected by downstream callers.
    debug : bool
        If True, appends a detailed "debug" key to each retrieved entry dictionary.

    Returns
    -------
    List[dict]
        Candidate knowledge entries each augmented with retrieval scores.
    """
    t0 = time.perf_counter()

    corpus_embeddings = build_corpus_embeddings()
    query_embedding = embed_query(observation)
    sims: np.ndarray = corpus_embeddings @ query_embedding  # shape (N,)

    # 1. Classify query domains and confidence
    query_domain_info = classify_domains(observation)
    query_domains = query_domain_info["domains"]
    query_conf = query_domain_info["confidence"]

    # 2. Normalize query and extract tokens/entities
    normalized_query = normalize_query(observation)
    query_tokens_all = normalized_query.split()
    query_tokens_filtered = {t for t in query_tokens_all if t not in MINIMAL_STOP_WORDS}
    query_entities = _extract_entities(observation)

    # ------------------------------------------------------------
    # Stage A: Candidate Generation
    # ------------------------------------------------------------
    # Retrieve dense cosine similarities for all entries and sort to get top pool
    all_candidates_dense = []
    for idx, entry in enumerate(KNOWLEDGE):
        all_candidates_dense.append({
            "entry": entry,
            "similarity": float(sims[idx])
        })
    # Sort descending by embedding similarity, ascending by ID as a tie-breaker
    all_candidates_dense.sort(key=lambda x: (-x["similarity"], x["entry"]["id"]))
    
    # Slice to pool size
    pool_items = all_candidates_dense[:CANDIDATE_POOL_SIZE]

    # ------------------------------------------------------------
    # Stage B: Candidate Selection & Filtering
    # ------------------------------------------------------------
    selected_pool = pool_items
    if query_domains:
        # Split pool into matching and non-matching domains
        matching_domain_items = []
        non_matching_domain_items = []
        for item in pool_items:
            entry_id = item["entry"]["id"]
            cand_domains = CANDIDATE_DOMAINS[entry_id]["domains"]
            if query_domains.intersection(cand_domains):
                matching_domain_items.append(item)
            else:
                non_matching_domain_items.append(item)
                
        # If matching count satisfies MIN_MATCHING_CANDIDATES threshold, filter to matching only
        if len(matching_domain_items) >= MIN_MATCHING_CANDIDATES:
            selected_pool = matching_domain_items

    # ------------------------------------------------------------
    # Stage C: Hybrid Reranking (Scores are computed directly from CosineSimilarity)
    # ------------------------------------------------------------
    scored_candidates = []
    for item in selected_pool:
        entry = item["entry"]
        entry_id = entry["id"]
        embedding_sim = item["similarity"]

        # Compute Keyword Overlap
        keyword_overlap = compute_weighted_keyword_overlap(query_tokens_filtered, CANDIDATE_TOKENS[entry_id])

        # Compute Entity Bonus
        candidate_entities = _extract_entities(CANDIDATE_TEXTS[entry_id])
        shared_entities = query_entities.intersection(candidate_entities)
        entity_bonus = min(MAX_ENTITY_BONUS, len(shared_entities) * ENTITY_BONUS)

        # Compute Phrase Bonus
        phrase_bonus = 0.0
        if is_exact_phrase_match(query_tokens_all, CANDIDATE_TOKEN_LISTS[entry_id]):
            phrase_bonus = EXACT_PHRASE_BONUS

        # Compute Domain Match Bonus
        cand_domain_info = CANDIDATE_DOMAINS[entry_id]
        cand_domains = cand_domain_info["domains"]
        cand_conf = cand_domain_info["confidence"]
        
        domain_bonus = 0.0
        if query_domains.intersection(cand_domains):
            domain_bonus = DOMAIN_MATCH_BONUS

        # Compute Category Match Bonus
        category_bonus = 0.0
        if check_category_alignment(entry.get("category", ""), query_domains):
            category_bonus = CATEGORY_MATCH_BONUS

        # Compute Technique Match Boost
        technique_bonus = 0.0
        technique_tokens = CANDIDATE_TOKENS[entry_id].get("technique", set())
        if query_tokens_filtered.intersection(technique_tokens):
            technique_bonus = TECHNIQUE_MATCH_BONUS

        # Compute Domain Mismatch Penalty
        domain_penalty = 0.0
        # Only penalize if BOTH query and candidate are confidently classified (>= 0.6) and share no domains
        if query_conf >= 0.60 and cand_conf >= 0.60:
            if not query_domains.intersection(cand_domains):
                domain_penalty = DOMAIN_MISMATCH_PENALTY

        # Cap total additive bonuses at 0.15
        total_bonus = min(0.15, domain_bonus + entity_bonus + phrase_bonus + category_bonus + technique_bonus)

        # Compute Hybrid Score using original SentenceTransformer cosine similarity (no normalization)
        raw_hybrid = (
            EMBEDDING_WEIGHT * embedding_sim
            + KEYWORD_WEIGHT * keyword_overlap
            + total_bonus
            - domain_penalty
        )
        hybrid_score = min(1.0, max(0.0, raw_hybrid))

        scored_candidates.append({
            "entry": entry,
            "similarity": embedding_sim,
            "keyword_overlap": round(keyword_overlap, 4),
            "domain_bonus": round(domain_bonus, 4),
            "domain_penalty": round(domain_penalty, 4),
            "entity_bonus": round(entity_bonus, 4),
            "phrase_bonus": round(phrase_bonus, 4),
            "category_bonus": round(category_bonus, 4),
            "technique_bonus": round(technique_bonus, 4),
            "hybrid_score": round(hybrid_score, 4),
            "matched_domains": query_domains.intersection(cand_domains),
            "matched_entities": shared_entities,
            "candidate_entities": candidate_entities
        })

    # Sort deterministically by: 1. hybrid_score DESC, 2. similarity DESC, 3. id ASC (tie-breakers)
    scored_candidates.sort(key=lambda x: (-x["hybrid_score"], -x["similarity"], x["entry"]["id"]))

    # Compute margin between Top-1 and Top-2
    margin = 1.0
    if len(scored_candidates) >= 2:
        margin = scored_candidates[0]["hybrid_score"] - scored_candidates[1]["hybrid_score"]

    # Calibrate confidence tiers
    for item in scored_candidates:
        score = item["hybrid_score"]
        overlap = item["keyword_overlap"]
        cand_domains = CANDIDATE_DOMAINS[item["entry"]["id"]]["domains"]
        cand_conf = CANDIDATE_DOMAINS[item["entry"]["id"]]["confidence"]
        cand_entities = item["candidate_entities"]

        domain_agreement = len(query_domains.intersection(cand_domains)) > 0
        entity_agreement = len(query_entities.intersection(cand_entities)) > 0
        
        domain_mismatch = (query_conf >= 0.60 and cand_conf >= 0.60 and not domain_agreement)
        entity_mismatch = (len(query_entities) > 0 and not entity_agreement)

        if score >= 0.70 and (domain_agreement or entity_agreement):
            tier = "high"
        elif score >= 0.45:
            tier = "medium"
        else:
            tier = "low"

        # Downgrade if both domain mismatch and entity mismatch occur
        if tier == "high" and domain_mismatch and entity_mismatch:
            tier = "medium"

        # Apply score margin safety downgrade
        if tier == "high" and margin < 0.05:
            tier = "medium"

        item["confidence"] = tier

    # Get top-k matches
    top_matches = scored_candidates[:k]

    elapsed = time.perf_counter() - t0
    if top_matches:
        logger.info(
            "Retrieval complete in %.3f s - top match: %s (hybrid score %.4f, original similarity %.4f)",
            elapsed,
            top_matches[0]["entry"]["id"],
            top_matches[0]["hybrid_score"],
            top_matches[0]["similarity"],
        )

    # Return candidates preserving original keys and adding new retrieval metrics
    res_list = []
    for item in top_matches:
        candidate_dict = {
            **item["entry"],
            "similarity": round(item["similarity"], 4),
            "hybrid_score": item["hybrid_score"],
            "keyword_overlap": item["keyword_overlap"],
            "entity_bonus": item["entity_bonus"],
            "confidence": item["confidence"],
        }
        if debug:
            candidate_dict["debug"] = {
                "embedding": round(item["similarity"], 4),
                "keyword": round(item["keyword_overlap"], 4),
                "domain_bonus": round(item["domain_bonus"], 4),
                "domain_penalty": round(item["domain_penalty"], 4),
                "entity_bonus": round(item["entity_bonus"], 4),
                "category_bonus": round(item["category_bonus"], 4),
                "phrase_bonus": round(item["phrase_bonus"], 4),
                "technique_bonus": round(item["technique_bonus"], 4),
                "matched_domains": sorted(list(item["matched_domains"])),
                "matched_entities": sorted(list(item["matched_entities"])),
            }
        res_list.append(candidate_dict)

    return res_list


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------


def _self_test() -> None:
    """Run the prescribed self-test query and print Top-5 results with scores.

    Exercises the complete pipeline path:
      corpus embedding (or cache load) -> query encoding ->
      cosine-similarity ranking -> result formatting.
    """
    query = (
        "The application behaves differently when whitespace is added to HTTP headers."
    )
    separator = "=" * 72
    print("\n" + separator)
    print("Self-test query:")
    print("  " + repr(query))
    print(separator)

    results = retrieve(query, k=5)

    header = "{:<6} {:<12} {:<8}  {}".format("Rank", "ID", "Score", "Title")
    print("\n" + header)
    print("-" * 72)
    for rank_pos, entry in enumerate(results, start=1):
        title = str(entry.get("title", ""))[:52]
        score = entry["similarity"]
        eid = entry["id"]
        print("{:<6} {:<12} {:<8.4f}  {}".format(rank_pos, eid, score, title))
    print(separator + "\n")


if __name__ == "__main__":
    _self_test()
