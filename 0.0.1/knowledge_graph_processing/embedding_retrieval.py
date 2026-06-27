"""
Embedding retrieval stage.

Converts each knowledge entry's trigger conditions and core knowledge text
into a vector representation, then matches a researcher's free-text
observation against that vector space to find the most relevant entries.

No internet-connected embedding model is available in this environment, so
vectors are produced with a TF-IDF bag-of-words scheme (numpy only). The
public contract `retrieve(observation) -> list[dict]` is what downstream
stages depend on, so the vectorization technique can be upgraded later
(e.g. to a transformer embedding) without changing any caller.
"""

import json
import re
from pathlib import Path

import numpy as np

DATA_DIR = Path(__file__).parent.parent / "experimental data" / "experimental data"
KNOWLEDGE_FILE = DATA_DIR / "experiential_knowledge_41.json"
CACHE_FILE = Path(__file__).parent / ".cache_corpus_vectors.npz"

KNOWLEDGE = json.loads(KNOWLEDGE_FILE.read_text(encoding="utf-8"))["knowledge"]
KNOWLEDGE_BY_ID = {k["id"]: k for k in KNOWLEDGE}

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def pull_text(entry: dict) -> str:
    """Build the text representation an entry is matched against: trigger conditions + knowledge."""
    return entry["knowledge"] + " " + " ".join(entry["trigger_condition"])


def embed_corpus() -> tuple[np.ndarray, list[str]]:
    """Build TF-IDF vectors for every entry in the corpus, caching the result to disk."""
    if CACHE_FILE.exists():
        cached = np.load(CACHE_FILE, allow_pickle=True)
        if list(cached["ids"]) == [k["id"] for k in KNOWLEDGE]:
            return cached["vectors"], list(cached["vocab"])

    docs_tokens = [_tokenize(pull_text(k)) for k in KNOWLEDGE]
    vocab = sorted({t for toks in docs_tokens for t in toks})
    vocab_index = {t: i for i, t in enumerate(vocab)}

    doc_freq = np.zeros(len(vocab))
    for toks in docs_tokens:
        for t in set(toks):
            doc_freq[vocab_index[t]] += 1
    idf = np.log((1 + len(docs_tokens)) / (1 + doc_freq)) + 1

    vectors = np.zeros((len(docs_tokens), len(vocab)))
    for row, toks in enumerate(docs_tokens):
        for t in toks:
            vectors[row, vocab_index[t]] += 1
        vectors[row] *= idf
        norm = np.linalg.norm(vectors[row])
        if norm > 0:
            vectors[row] /= norm

    np.savez(
        CACHE_FILE,
        vectors=vectors,
        vocab=np.array(vocab),
        ids=np.array([k["id"] for k in KNOWLEDGE]),
        idf=idf,
    )
    return vectors, vocab


def embed_query(observation: str) -> np.ndarray:
    """Vectorize a researcher's observation in the same TF-IDF space as the corpus."""
    corpus_vectors, vocab = embed_corpus()
    cached = np.load(CACHE_FILE, allow_pickle=True)
    idf = cached["idf"]
    vocab_index = {t: i for i, t in enumerate(vocab)}

    vec = np.zeros(len(vocab))
    for t in _tokenize(observation):
        if t in vocab_index:
            vec[vocab_index[t]] += 1
    vec *= idf
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec /= norm
    return vec


def top_k_similar(query_vec: np.ndarray, k: int = 3) -> list[tuple[str, float]]:
    """Rank corpus entries by cosine similarity to the query vector, returning the top k."""
    corpus_vectors, _ = embed_corpus()
    sims = corpus_vectors @ query_vec
    order = np.argsort(-sims)[:k]
    ids = [k["id"] for k in KNOWLEDGE]
    return [(ids[i], float(sims[i])) for i in order]


def retrieve(observation: str) -> list[dict]:
    """Public entry point: top-3 candidate knowledge entries with a similarity score attached."""
    query_vec = embed_query(observation)
    matches = top_k_similar(query_vec, k=3)
    return [{**KNOWLEDGE_BY_ID[entry_id], "similarity": round(score, 4)} for entry_id, score in matches]


def _test_vs_examples() -> None:
    """Sanity check: confirm known observations surface the expected entry in their top-3."""
    examples = [
        (
            "I'm proxying requests through gopher and noticed CRLF sequences are tolerated "
            "inside the gopher URI without rejection",
            "ek_0002",
        ),
        (
            "curl followed a redirect from a proxied connection to a direct connection and "
            "the Proxy-Authorization header was still attached",
            "ek_0000",
        ),
    ]
    for observation, expected_id in examples:
        results = retrieve(observation)
        top_ids = [r["id"] for r in results]
        status = "PASS" if expected_id in top_ids else "FAIL"
        print(f"{status}: expected {expected_id} in top-3 {top_ids}")


if __name__ == "__main__":
    _test_vs_examples()
