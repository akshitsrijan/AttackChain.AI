"""
Embedding retrieval stage - domain-agnostic transformer-based semantic search.

Converts each knowledge entry into a dense sentence embedding using the
``sentence-transformers/all-MiniLM-L6-v2`` model, retrieves a wide candidate
pool by cosine similarity, then reranks that pool with a cross-encoder
(``cross-encoder/ms-marco-MiniLM-L-6-v2``) for finer-grained relevance
judgement before returning the top-k.

The public contract ``retrieve(observation) -> list[dict]`` is unchanged, so
all downstream stages (quality_ranking, graph_traversal, response_synthesis)
continue to work without modification.

Design note - why there is no hardcoded domain/keyword system here:
A previous version of this module classified observations into fixed
cybersecurity "domains" (WEB_ATTACK, MALWARE, etc.) using hand-curated
keyword lists, and used domain agreement to hand out bonuses/penalties.
That approach does not generalize: any keyword generic enough to appear
across many entries (e.g. "http", "payload") silently mis-tags unrelated
entries, and every new technology (cloud, ICS, mobile, AD...) would need its
own keyword list maintained forever. This version instead leans on the
embedding model and cross-encoder - both trained for general-purpose
semantic relevance - for the semantic signal, and limits hand-written logic
to things that are genuinely domain-agnostic and structurally generalizable:
weighted lexical field overlap, exact-phrase matching, and extraction of
*generic, structurally-recognizable identifiers* (CVE/CWE/CAPEC/MITRE
ATT&CK IDs, RFC numbers, IP addresses, version numbers) rather than a fixed
vocabulary of product/technique names.

Corpus embeddings are cached to disk as a ``.npz`` file and are regenerated
whenever the corpus content, entry IDs, or embedding model change (detected
via an MD5 fingerprint of the built document text).
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
from sentence_transformers import CrossEncoder, SentenceTransformer

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

# Hybrid score = EMBEDDING_WEIGHT * embedding_sim
#              + CROSSENCODER_WEIGHT * cross_encoder_score
#              + KEYWORD_WEIGHT * weighted_keyword_overlap
#              + (entity_bonus + phrase_bonus, capped at MAX_TOTAL_BONUS)
#
# The cross-encoder is weighted most heavily: unlike the embedding model
# (which encodes query and document independently), it sees both texts
# together and is specifically trained to judge relevance, so it is the
# strongest available semantic signal once a wide-enough candidate pool has
# been gathered by the (cheaper) embedding-similarity pass.
EMBEDDING_WEIGHT: float = 0.30
CROSSENCODER_WEIGHT: float = 0.50
KEYWORD_WEIGHT: float = 0.20

ENTITY_BONUS: float = 0.02
MAX_ENTITY_BONUS: float = 0.08
EXACT_PHRASE_BONUS: float = 0.05
MAX_TOTAL_BONUS: float = 0.10

#: Size of the dense (embedding-similarity) candidate pool handed to the
#: cross-encoder for reranking. Wide enough that a genuinely relevant entry
#: is rarely excluded before the more precise reranking stage sees it.
CANDIDATE_POOL_SIZE: int = 50

#: Confidence-tier thresholds, expressed purely in terms of retrieval
#: quality (final hybrid score and the margin over the runner-up) rather
#: than any domain-specific heuristic - see classify_domains' removal note
#: above. A poor match should read as low-confidence regardless of topic.
HIGH_CONFIDENCE_SCORE: float = 0.70
HIGH_CONFIDENCE_MARGIN: float = 0.05
MEDIUM_CONFIDENCE_SCORE: float = 0.45

#: Fields present on every knowledge entry, weighted by how strongly a
#: lexical match in that field signals relevance. Updated to match the
#: actual corpus schema (title/category/trigger_condition/knowledge/
#: abstracted_pattern/chain_potential/pitfalls/applicable_to) - the field
#: set is fixed by the dataset, not hardcoded to any particular technology.
FIELD_WEIGHTS: dict[str, float] = {
    "title": 3.0,
    "category": 1.0,
    "trigger_condition": 2.0,
    "knowledge": 2.0,
    "abstracted_pattern": 1.5,
    "chain_potential": 1.0,
    "pitfalls": 1.0,
    "applicable_to": 1.0,
}

MINIMAL_STOP_WORDS: set[str] = {
    "a", "an", "the", "and", "or", "but", "is", "are", "was", "were",
    "of", "to", "for", "in", "on", "at", "by", "with", "from", "it",
    "its", "this", "that", "these", "those"
}

#: Generic cybersecurity abbreviations expanded before embedding so the
#: model sees the spelled-out form it is more likely to have strong
#: representations for. This is a lightweight acronym->phrase lookup, not a
#: domain classifier, so it does not have the generalization problem the
#: removed DOMAIN_KEYWORDS/SYNONYM_GROUPS system had.
ABBREVIATIONS: dict[str, str] = {
    "rdp": "remote desktop protocol",
    "smb": "server message block",
    "ad": "active directory",
    "lsass": "local security authority subsystem service",
    "c2": "command and control",
    "mfa": "multi-factor authentication",
    "vpn": "virtual private network",
    "av": "antivirus",
}

# ---------------------------------------------------------------------------
# Generic, structurally-recognizable entity patterns
# ---------------------------------------------------------------------------
# These extract identifiers whose *shape* signals relevance regardless of
# which technology they belong to, so a CVE or version number for a product
# released tomorrow is still recognized without touching this code.

CVE_PATTERN = re.compile(r"\bcve-\d{4}-\d{4,}\b", re.IGNORECASE)
CWE_PATTERN = re.compile(r"\bcwe-\d{1,4}\b", re.IGNORECASE)
CAPEC_PATTERN = re.compile(r"\bcapec-\d{1,4}\b", re.IGNORECASE)
MITRE_PATTERN = re.compile(r"\b(?:t\d{4}(?:\.\d{3})?|ta\d{4}|s\d{4}|g\d{4}|m\d{4})\b", re.IGNORECASE)
RFC_PATTERN = re.compile(r"\brfc-?\s?\d{2,5}\b", re.IGNORECASE)
IPV4_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
VERSION_PATTERN = re.compile(r"\bv?\d+\.\d+(?:\.\d+){0,2}\b", re.IGNORECASE)

_ENTITY_PATTERNS: tuple[re.Pattern, ...] = (
    CVE_PATTERN, CWE_PATTERN, CAPEC_PATTERN, MITRE_PATTERN,
    RFC_PATTERN, IPV4_PATTERN, VERSION_PATTERN,
)

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
    for abbr, expansion in ABBREVIATIONS.items():
        text = re.sub(r"\b" + re.escape(abbr) + r"\b", expansion, text)
    return text


def normalize_query(query: str) -> str:
    """Normalize query text: lowercase, remove punctuation, expand abbreviations."""
    return expand_abbreviations(normalize_only(query))


def get_embedding_query(query: str) -> str:
    """Pipeline for query embedding: normalize -> expand abbreviations."""
    return normalize_query(query)


# ---------------------------------------------------------------------------
# Score Calculation Helpers
# ---------------------------------------------------------------------------

def _extract_entities(text: str) -> set[str]:
    """Extract structurally-recognizable identifiers (CVE/CWE/CAPEC/MITRE
    ATT&CK IDs, RFC numbers, IP addresses, version numbers) case-insensitively.

    Deliberately pattern-based rather than a fixed vocabulary: a new CVE or
    a new product's version string is recognized without editing this file.
    """
    lowered = text.lower()
    entities: set[str] = set()
    for pattern in _ENTITY_PATTERNS:
        entities.update(pattern.findall(lowered))
    return entities


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


# ---------------------------------------------------------------------------
# Paths and constants
# ---------------------------------------------------------------------------

DATA_DIR: Path = (
    Path(__file__).parent.parent / "experimental data" / "experimental data"
)
KNOWLEDGE_FILE: Path = DATA_DIR / "experiential_knowledge_41.json"
CACHE_FILE: Path = Path(__file__).parent / ".cache_corpus_embeddings.npz"
MODEL_NAME: str = "sentence-transformers/all-MiniLM-L6-v2"
CROSS_ENCODER_MODEL_NAME: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

# ---------------------------------------------------------------------------
# Knowledge base - loaded once at module import
# ---------------------------------------------------------------------------

KNOWLEDGE: List[dict] = json.loads(
    KNOWLEDGE_FILE.read_text(encoding="utf-8")
)["knowledge"]
KNOWLEDGE_BY_ID: dict = {entry["id"]: entry for entry in KNOWLEDGE}

# Metadata fields that describe provenance/bookkeeping rather than the
# entry's actual security content - excluded from the document text used
# for embedding, keyword fields, and entity extraction.
_METADATA_FIELDS: frozenset[str] = frozenset(
    {"id", "source_id", "extracted_at", "confidence_rationale", "shelf_life", "confidence"}
)


def _stringify(value) -> str:
    """Flatten a str/list/dict knowledge-entry value into plain text."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(_stringify(v) for v in value)
    if isinstance(value, dict):
        return " ".join(_stringify(v) for v in value.values())
    return str(value) if value else ""


def _field_text(entry: dict, field: str) -> str:
    """Return the flattened text for one field of one knowledge entry."""
    return _stringify(entry.get(field, ""))


def _build_document(entry: dict) -> str:
    """Build the single combined text document representing one knowledge
    entry, used both for embedding and for all downstream lexical/entity
    analysis on that entry.

    Every non-metadata field is included (title, category, trigger_condition,
    knowledge, abstracted_pattern, chain_potential, pitfalls, applicable_to,
    knowledge_type, and any future field the dataset adds) so the document
    representation does not need to change as the corpus grows into new
    technology areas - it concatenates whatever descriptive content an entry
    has rather than a fixed list tuned to today's fields.

    Parameters
    ----------
    entry : dict
        A single knowledge entry from the corpus.

    Returns
    -------
    str
        A single space-joined string ready for encoding.
    """
    parts: List[str] = [
        _stringify(value)
        for key, value in entry.items()
        if key not in _METADATA_FIELDS and value
    ]
    return " ".join(part for part in parts if part)


# ---------------------------------------------------------------------------
# Startup precomputation and caching (in-memory, no dataset mutation)
# ---------------------------------------------------------------------------

CANDIDATE_TEXTS: dict[str, str] = {}
CANDIDATE_TOKENS: dict[str, dict[str, set[str]]] = {}
CANDIDATE_TOKEN_LISTS: dict[str, list[str]] = {}


def _precompute_candidates() -> None:
    global CANDIDATE_TEXTS, CANDIDATE_TOKENS, CANDIDATE_TOKEN_LISTS
    for entry in KNOWLEDGE:
        entry_id = entry["id"]

        normalized_combined = normalize_only(_build_document(entry))
        CANDIDATE_TOKEN_LISTS[entry_id] = normalized_combined.split()
        CANDIDATE_TEXTS[entry_id] = normalized_combined

        field_tokens: dict[str, set[str]] = {}
        for field in FIELD_WEIGHTS:
            norm_field = normalize_only(_field_text(entry, field))
            tokens = {t for t in norm_field.split() if t not in MINIMAL_STOP_WORDS}
            if tokens:
                field_tokens[field] = tokens
        CANDIDATE_TOKENS[entry_id] = field_tokens


# Run precomputation
_precompute_candidates()


# ---------------------------------------------------------------------------
# Model singletons
# ---------------------------------------------------------------------------

_model: SentenceTransformer | None = None
_cross_encoder: CrossEncoder | None = None


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


def _get_cross_encoder() -> CrossEncoder:
    """Return the shared CrossEncoder reranking model, loading it on first call.

    Unlike the SentenceTransformer (which encodes query and document
    independently), the cross-encoder scores a (query, document) pair
    jointly, giving a more precise relevance judgement at the cost of being
    too slow to run over the whole corpus - hence it only reranks the
    embedding-similarity candidate pool, not all entries.
    """
    global _cross_encoder
    if _cross_encoder is None:
        logger.info("Loading CrossEncoder reranking model: %s", CROSS_ENCODER_MODEL_NAME)
        _cross_encoder = CrossEncoder(CROSS_ENCODER_MODEL_NAME)
        logger.info("CrossEncoder model loaded successfully.")
    return _cross_encoder


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------


def _corpus_fingerprint() -> str:
    """Return an MD5 hex digest that uniquely identifies the current corpus.

    The digest is computed over the ordered list of entry IDs, the built
    document text for every entry, and the embedding model name, so that any
    addition, removal, reordering, content edit, or model change invalidates
    the cache. Hashing only IDs would let stale embeddings from a
    since-changed document-building pipeline or model survive indefinitely,
    since IDs never change.

    Returns
    -------
    str
        32-character lowercase hex string.
    """
    documents = [_build_document(entry) for entry in KNOWLEDGE]
    fingerprint_source = {
        "ids": [entry["id"] for entry in KNOWLEDGE],
        "documents": documents,
        "model": MODEL_NAME,
    }
    return hashlib.md5(
        json.dumps(fingerprint_source, sort_keys=True).encode("utf-8")
    ).hexdigest()


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


def _normalized_cross_encoder_scores(observation: str, pool_entries: List[dict]) -> dict[str, float]:
    """Score every pooled entry against the observation with the cross-encoder.

    Raw cross-encoder output is not guaranteed to lie in [0, 1] (it depends
    on the model's training objective), so scores are min-max normalised
    across the candidate pool. Only relative ordering within the pool is
    needed for reranking, which this preserves regardless of the model's
    native output scale.

    Parameters
    ----------
    observation : str
        The raw (unprocessed) researcher observation.
    pool_entries : List[dict]
        Knowledge entries in the embedding-similarity candidate pool.

    Returns
    -------
    dict[str, float]
        entry_id -> normalised cross-encoder relevance score in [0, 1].
    """
    if not pool_entries:
        return {}

    pairs = [(observation, CANDIDATE_TEXTS[entry["id"]]) for entry in pool_entries]
    raw_scores = np.asarray(_get_cross_encoder().predict(pairs), dtype=np.float32)

    cmin = float(raw_scores.min())
    cmax = float(raw_scores.max())
    spread = cmax - cmin

    if spread <= 1e-9:
        # All pooled candidates scored identically (e.g. pool size 1) -
        # no relative signal to extract, so treat them as neutral.
        return {entry["id"]: 0.5 for entry in pool_entries}

    return {
        entry["id"]: float((score - cmin) / spread)
        for entry, score in zip(pool_entries, raw_scores)
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def retrieve(observation: str, k: int = 3, debug: bool = False) -> List[dict]:
    """Return the top-k candidate knowledge entries for the given observation.

    Pipeline: embedding similarity gathers a wide candidate pool ->
    cross-encoder reranks that pool with joint (query, document) relevance
    scoring -> a hybrid score blends cross-encoder relevance, embedding
    similarity, weighted lexical field overlap, and small bonuses for
    shared structurally-recognizable identifiers (CVE/CWE/MITRE/RFC/IP/
    version) or an exact phrase match -> top-k by hybrid score.

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

    normalized_query = normalize_query(observation)
    query_tokens_all = normalized_query.split()
    query_tokens_filtered = {t for t in query_tokens_all if t not in MINIMAL_STOP_WORDS}
    query_entities = _extract_entities(observation)

    # ------------------------------------------------------------
    # Stage A: Dense candidate pool (embedding similarity over the whole corpus)
    # ------------------------------------------------------------
    order = sorted(
        range(len(KNOWLEDGE)),
        key=lambda i: (-float(sims[i]), KNOWLEDGE[i]["id"]),
    )
    pool_indices = order[:CANDIDATE_POOL_SIZE]
    pool_entries = [KNOWLEDGE[i] for i in pool_indices]
    embedding_sims: dict[str, float] = {
        KNOWLEDGE[i]["id"]: float(sims[i]) for i in pool_indices
    }

    # ------------------------------------------------------------
    # Stage B: Cross-encoder reranking of the pool
    # ------------------------------------------------------------
    cross_scores = _normalized_cross_encoder_scores(observation, pool_entries)

    # ------------------------------------------------------------
    # Stage C: Hybrid scoring
    # ------------------------------------------------------------
    scored_candidates = []
    for entry in pool_entries:
        entry_id = entry["id"]
        embedding_sim = embedding_sims[entry_id]
        cross_score = cross_scores[entry_id]

        keyword_overlap = compute_weighted_keyword_overlap(query_tokens_filtered, CANDIDATE_TOKENS[entry_id])

        candidate_entities = _extract_entities(CANDIDATE_TEXTS[entry_id])
        shared_entities = query_entities.intersection(candidate_entities)
        entity_bonus = min(MAX_ENTITY_BONUS, len(shared_entities) * ENTITY_BONUS)

        phrase_bonus = 0.0
        if is_exact_phrase_match(query_tokens_all, CANDIDATE_TOKEN_LISTS[entry_id]):
            phrase_bonus = EXACT_PHRASE_BONUS

        total_bonus = min(MAX_TOTAL_BONUS, entity_bonus + phrase_bonus)

        raw_hybrid = (
            EMBEDDING_WEIGHT * embedding_sim
            + CROSSENCODER_WEIGHT * cross_score
            + KEYWORD_WEIGHT * keyword_overlap
            + total_bonus
        )
        hybrid_score = min(1.0, max(0.0, raw_hybrid))

        scored_candidates.append({
            "entry": entry,
            "similarity": embedding_sim,
            "cross_score": round(cross_score, 4),
            "keyword_overlap": round(keyword_overlap, 4),
            "entity_bonus": round(entity_bonus, 4),
            "phrase_bonus": round(phrase_bonus, 4),
            "hybrid_score": round(hybrid_score, 4),
            "matched_entities": shared_entities,
            "candidate_entities": candidate_entities,
        })

    # Sort deterministically by: 1. hybrid_score DESC, 2. similarity DESC, 3. id ASC (tie-breakers)
    scored_candidates.sort(key=lambda x: (-x["hybrid_score"], -x["similarity"], x["entry"]["id"]))

    # Compute margin between Top-1 and Top-2
    margin = 1.0
    if len(scored_candidates) >= 2:
        margin = scored_candidates[0]["hybrid_score"] - scored_candidates[1]["hybrid_score"]

    # Calibrate confidence tiers purely from retrieval quality (final score
    # and margin over the runner-up), not from any domain heuristic - a
    # weak match should read as low-confidence regardless of topic.
    for item in scored_candidates:
        score = item["hybrid_score"]
        entity_agreement = len(query_entities.intersection(item["candidate_entities"])) > 0

        if score >= HIGH_CONFIDENCE_SCORE and margin >= HIGH_CONFIDENCE_MARGIN:
            tier = "high"
        elif score >= MEDIUM_CONFIDENCE_SCORE:
            tier = "medium"
        else:
            tier = "low"

        # A "high" call with zero corroborating entity overlap and only a
        # bare-minimum margin is still worth a sanity downgrade.
        if tier == "high" and not entity_agreement and margin < HIGH_CONFIDENCE_MARGIN * 2:
            tier = "medium"

        item["confidence"] = tier

    # Get top-k matches
    top_matches = scored_candidates[:k]

    elapsed = time.perf_counter() - t0
    if top_matches:
        logger.info(
            "Retrieval complete in %.3f s - top match: %s (hybrid score %.4f, "
            "embedding similarity %.4f, cross-encoder score %.4f)",
            elapsed,
            top_matches[0]["entry"]["id"],
            top_matches[0]["hybrid_score"],
            top_matches[0]["similarity"],
            top_matches[0]["cross_score"],
        )

    # Return candidates preserving original keys and adding new retrieval metrics
    res_list = []
    for item in top_matches:
        candidate_dict = {
            **item["entry"],
            "similarity": round(item["similarity"], 4),
            "hybrid_score": item["hybrid_score"],
            "cross_score": item["cross_score"],
            "keyword_overlap": item["keyword_overlap"],
            "entity_bonus": item["entity_bonus"],
            "confidence": item["confidence"],
        }
        if debug:
            candidate_dict["debug"] = {
                "embedding": round(item["similarity"], 4),
                "cross_score": item["cross_score"],
                "keyword": round(item["keyword_overlap"], 4),
                "entity_bonus": round(item["entity_bonus"], 4),
                "phrase_bonus": round(item["phrase_bonus"], 4),
                "matched_entities": sorted(item["matched_entities"]),
            }
        res_list.append(candidate_dict)

    return res_list


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print_results_table(results: List[dict]) -> None:
    """Print a Top-k results table for a list of ``retrieve()`` output dicts."""
    separator = "=" * 90
    header = "{:<6} {:<12} {:<8} {:<8} {:<8} {:<8}  {}".format(
        "Rank", "ID", "Sim", "Cross", "Hybrid", "Conf", "Title"
    )
    print("\n" + header)
    print("-" * 90)
    for rank_pos, entry in enumerate(results, start=1):
        title = str(entry.get("title", ""))[:40]
        print("{:<6} {:<12} {:<8.4f} {:<8.4f} {:<8.4f} {:<8}  {}".format(
            rank_pos,
            entry["id"],
            entry["similarity"],
            entry["cross_score"],
            entry["hybrid_score"],
            entry["confidence"],
            title,
        ))
    print(separator + "\n")


if __name__ == "__main__":
    observation = input("Enter a security observation: ").strip()
    if observation:
        _print_results_table(retrieve(observation, k=5))
    else:
        print("No observation entered.")
