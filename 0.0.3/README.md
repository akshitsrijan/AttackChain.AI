# AttackChain.AI

# AttackChain Advisor

An AI-powered reasoning assistant that takes a security researcher's
free-text observation, retrieves the most relevant entry from a curated
offensive-security knowledge base, weighs it against a quality scorecard,
traces the attack chain it belongs to, and synthesizes a grounded advisory
response.

## How it works

```
Researcher observation
        |
        v
Intent Extraction     -> (Ollama, optional) distills a noisy observation
                          into a concise security intent
        |
        v
Embedding Retrieval   -> sentence-embedding similarity search + cross-encoder
                          rerank -> top candidate knowledge entries
        |
        v
Quality Ranking       -> re-scores candidates by similarity x quality, assigns
                          a confidence tier
        |
        v
Graph Traversal       -> follows the cross-reference graph from the top entry
                          to find the next/previous steps in the attack chain
        |
        v
Consistency Validation -> checks the matched entry/chain against the
                           original observation before generating text
        |
        v
Response Synthesis   -> combines all of the above into a structured
                          template and generates a grounded advisory via a
                          local LLM (Ollama)
```

See `experimental data/figures/overall_pipeline.png` for the original
pipeline diagram.

## Datasets

All three datasets live in `experimental data/experimental data/` and are
explained in detail in `instructions.md`:

- **`experiential_knowledge_41.json`** — 41 structured offensive-security
  knowledge entries (trigger conditions, abstracted IF/THEN patterns,
  pitfalls, confidence, shelf-life).
- **`quality_metrics.json`** — an 8-point quality scorecard per entry (e.g.
  does the trigger describe a situation rather than an action, is a pitfall
  present, is confidence justified).
- **`cross_references.json`** — a directed graph of complementary entry
  pairs and suggested multi-step attack chains, extending beyond the 41
  curated entries to `ek_0253`.

## Project structure

```
0.0.3/
├── README.md
├── instructions.md                  Dataset explanations and solution proposal
├── attackchain_advisor.py           Standalone, single-file LLM-driven prototype
├── app.py                            Streamlit dashboard visualizing every pipeline stage
├── pipeline_diagrams.py             Generates the figures under experimental data/figures
├── visualise.py                     Dataset visualizations
├── run_benchmark.py                  Retrieval accuracy benchmark
├── verify_retrieval.py               Retrieval sanity checks
├── test_fixtures.json               Static fixtures for pipeline-combination tests
├── test_pipeline_combination.py     Tests retrieval->ranking->traversal combination logic against fixtures
├── *_Review.md                      Design rationale / before-after notes per stage
├── experimental data/
│   ├── experimental data/           The three source JSON datasets
│   └── figures/                     Generated charts and pipeline diagrams
└── pipeline/                        The modular, importable pipeline (see below)
    ├── embedding_retrieval.py       Retrieval stage: sentence-embedding + cross-encoder rerank
    ├── quality_ranking.py          Ranking stage: quality-adjusted scoring
    ├── graph_traversal.py          Chain stage: cross-reference graph traversal
    ├── response_synthesis.py       Synthesis stage: intent extraction, validation, LLM call
    └── main.py                     Orchestrator wiring all stages + CLI
```

### `pipeline/` modules

- **`embedding_retrieval.py`** — Embeds each knowledge entry's trigger
  conditions and core knowledge text with
  `sentence-transformers/all-MiniLM-L6-v2` (cached to disk, auto-invalidated
  via an MD5 fingerprint of the corpus text), retrieves a candidate pool by
  cosine similarity, then reranks that pool with a cross-encoder
  (`cross-encoder/ms-marco-MiniLM-L-6-v2`) for finer relevance judgement.
  Exposes `retrieve(observation) -> list[dict]`, returning the top candidate
  entries with a `similarity` score.
- **`quality_ranking.py`** — Loads the quality scorecard and computes
  `composite_score = similarity * (pass_count / 8)`, discounting similarity
  by how well-validated an entry is. Assigns `confidence_tier` (`"high"`
  only at a perfect 8/8). Exposes `rank(candidates) -> list[dict]`.
- **`graph_traversal.py`** — Builds a directed graph from the
  complementary-pairs data and walks up to 2 hops forward/backward from a
  matched entry. Flags any neighbor outside the curated 41-entry set rather
  than dropping it silently. Exposes `get_chain_context(entry_id) -> dict`.
- **`response_synthesis.py`** — Runs intent extraction, combines the
  top-ranked entry and its chain context into a structured response
  template, validates consistency across the retrieval/ranking/graph
  results, then prompts a local LLM (via **Ollama**, `qwen2.5vl:3b` by
  default) to produce a natural-language advisory grounded strictly in
  that data. Falls back to a local template if Ollama is unavailable or the
  call fails. Exposes a single `analyze(observation)` entry point that runs
  the whole pipeline and returns one structured result dict.
- **`main.py`** — Orchestrates `analyze()` end to end and exposes it as a
  CLI.

## Setup

```bash
cd "AttackChain.AI/0.0.3"
python -m venv .venv
.venv\Scripts\activate          # or: source .venv/Scripts/activate on Git Bash
pip install sentence-transformers numpy networkx pandas plotly streamlit matplotlib
```

The first run will download the embedding model (`all-MiniLM-L6-v2`) and
cross-encoder model (`ms-marco-MiniLM-L-6-v2`) from Hugging Face — this
requires an internet connection once; they're cached locally afterward.

Response synthesis requires a local Ollama server:

```bash
ollama serve
ollama pull qwen2.5vl:3b        # or set OLLAMA_MODEL to a model you have
```

If `ollama serve` isn't running, the pipeline still runs end-to-end and
produces a locally-templated advisory instead of an LLM-generated one.

## Usage

Run a single observation through the full pipeline, including LLM-generated
advisory text:

```bash
cd pipeline
python main.py "I noticed CRLF sequences are tolerated inside a gopher:// URI without rejection"
```

Run each stage's standalone self-tests:

```bash
python embedding_retrieval.py
python quality_ranking.py
python graph_traversal.py
python response_synthesis.py
```

Run the fixture-based combination tests (no LLM, no live data dependency):

```bash
cd ..
python test_pipeline_combination.py
```

Run retrieval accuracy benchmarking/verification:

```bash
python verify_retrieval.py
python run_benchmark.py
```

Run the Streamlit dashboard to visualize every pipeline stage (matched
entry, confidence tier, attack chain graph, execution time, and which
model/fallback path answered):

```bash
streamlit run app.py
```

## Notes

- `embedding_retrieval.py` uses real sentence-transformer embeddings with a
  cross-encoder reranking pass rather than a from-scratch TF-IDF vectorizer
  (see `0.0.1` for the original TF-IDF version). The `retrieve()` contract
  is stable, so the vectorization technique can be upgraded later without
  changing any caller.
- `response_synthesis.py` uses a local Ollama call for LLM generation
  (`OLLAMA_HOST`/`OLLAMA_MODEL` env vars override the defaults of
  `http://localhost:11434` / `qwen2.5vl:3b`) rather than a hosted API, so no
  API key is required.
- `attackchain_advisor.py` is an earlier, self-contained single-file
  prototype of the same idea (LLM-driven matching instead of embedding
  retrieval) kept for reference; `pipeline/` is the actively maintained,
  modular implementation.
- The `*_Review.md` documents record the design rationale and before/after
  analysis for each stage — read these if you want the "why" behind a
  specific stage's current implementation.
