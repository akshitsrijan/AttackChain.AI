# Semantic Retrieval Enhancement Review

This document reviews the targeted enhancements made to the semantic retrieval stage of the AttackChain Advisor to improve retrieval accuracy while maintaining full backward compatibility with downstream modules.

---

## 1. Implemented Improvements

### A. Preprocessing & Query Normalization
A modular preprocessing pipeline has been added to `pipeline/embedding_retrieval.py` executing strictly in this order:
1. **Normalize**: The query is converted to lowercase, redundant punctuation is stripped from word boundaries (preserving internal punctuation like in `CVE-2023-1234` or `location.pathname`), and whitespace is normalized.
2. **Abbreviation Expansion**: Common cybersecurity abbreviations are expanded using regex whole-word boundaries (e.g. `RDP` -> `remote desktop protocol`, `SMB` -> `server message block`, `AD` -> `active directory`, `LSASS` -> `local security authority subsystem service`, `C2` -> `command and control`, `MFA` -> `multi-factor authentication`, `VPN` -> `virtual private network`, `AV` -> `antivirus`).

### B. Cybersecurity Synonym Expansion
A lightweight synonym dictionary (`SYNONYM_GROUPS`) was created. Synonym expansion triggers when any variant (abbreviation or expansion) is matched in the normalized query. The matched synonym expansions (up to 6 terms) are appended for embedding generation only, keeping the original observation unchanged.

### C. Hybrid Scoring Pipeline
The retrieval similarity score is calculated by combining dense semantic similarity and weighted keyword overlap:
$$\text{Raw Hybrid} = \text{EMBEDDING\_WEIGHT} \times \text{Similarity} + \text{KEYWORD\_WEIGHT} \times \text{KeywordOverlap} + \text{EntityBonus} + \text{PhraseBonus}$$
$$\text{Hybrid Score} = \min(1.0, \max(0.0, \text{Raw Hybrid}))$$

Where:
- **EMBEDDING_WEIGHT** = 0.75
- **KEYWORD_WEIGHT** = 0.25
- **Similarity**: Cosine similarity from the SentenceTransformer model.
- **KeywordOverlap**: Weighted keyword overlap comparing normalized stop-word-filtered query tokens against candidate fields with differing weights:
  - `title`: $\times 3.0$
  - `technique`: $\times 3.0$
  - `tags`: $\times 2.0$
  - `summary`: $\times 2.0$
  - `recommendations` / `pitfalls` / `category`: $\times 1.0$
- **EntityBonus**: $+0.02$ per unique matching entity (CVE ID, MITRE ID, or custom terms like `mimikatz`, `powershell`, `lsass`) shared between query and candidate, capped at `MAX_ENTITY_BONUS = 0.10`.
- **PhraseBonus**: $+0.05$ exact contiguous token sequence phrase bonus if the query's normalized tokens appear in that exact order in the candidate.

### D. Startup Precomputation & Caching
To maintain high performance, normalized candidate texts and field token sets are precomputed once at startup when the module is imported:
- `CANDIDATE_TEXTS`: Dict of `entry_id` -> normalized combined text.
- `CANDIDATE_TOKENS`: Dict of `entry_id` -> Dict of `field` -> Set of filtered tokens.
- `CANDIDATE_TOKEN_LISTS`: Dict of `entry_id` -> list of all normalized tokens (for phrase matching).

No dataset files are modified or rewritten.

### E. Deterministic Sorting & Tie-Breaking
Candidates are sorted deterministically:
`hybrid_score DESC`, then `id ASC` (alphabetical tie-breaker).

### F. Confidence Calibration
Tiers are assigned dynamically based on similarity score, keyword overlap, and the score margin between the Top-1 and Top-2 candidates. If the margin is $< 0.05$, `"high"` confidence is downgraded to `"medium"` to prevent false high-confidence assertions.

---

## 2. Complexity Analysis
- **Startup overhead**: One-time tokenization and normalization of the 41-entry knowledge base (runs in $< 5\text{ms}$).
- **Embedding Generation**: Stays at $1$ query encoding call to SentenceTransformer.
- **Scoring Complexity**: Linear scanning of 41 candidates. Keyword overlap set operations and regex entity matching run in $< 1\text{ms}$ total.

---

## 3. Compatibility & Verification

No public APIs or return schemas were modified.
- `retrieve(observation, k=3) -> List[dict]` is fully preserved.
- `embed_query(query) -> np.ndarray` is preserved.
- `top_k_similar(query_embedding, corpus_embeddings, k=5) -> List[Tuple[str, float]]` is preserved.
- No existing dict keys are renamed or removed. All new fields (`hybrid_score`, `keyword_overlap`, `entity_bonus`, `confidence`) are appended.

Unit tests (`verify_retrieval.py`) check all logic. The benchmark runner (`run_benchmark.py`) validates retrieval performance against 15 test queries and writes results to `Retrieval_Benchmark.md`.
