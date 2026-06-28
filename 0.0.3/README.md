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
Embedding Retrieval   -> top-3 candidate knowledge entries (similarity score)
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
Response Synthesis    -> combines all of the above into a structured
                          template and generates a grounded advisory via a
                          local LLM
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
DATAPORT/
├── README.md
├── instructions.md                  Dataset explanations and solution proposal
├── attackchain_advisor.py           Standalone, single-file LLM-driven prototype
├── pipeline_diagrams.py             Generates the figures under experimental data/figures
├── visualise.py                     Dataset visualizations
├── test_fixtures.json               Static fixtures for pipeline-combination tests
├── test_pipeline_combination.py     Tests retrieval->ranking->traversal combination logic against fixtures
├── experimental data/
│   ├── experimental data/           The three source JSON datasets
│   └── figures/                     Generated charts and pipeline diagrams
└── pipeline/                        The modular, importable pipeline (see below)
    ├── embedding_retrieval.py       Retrieval stage: TF-IDF similarity search
    ├── quality_ranking.py          Ranking stage: quality-adjusted scoring
    ├── graph_traversal.py          Chain stage: cross-reference graph traversal
    ├── response_synthesis.py       Synthesis stage: response template + LLM call
    └── main.py                     Orchestrator wiring all four stages + CLI
```

### `pipeline/` modules

- **`embedding_retrieval.py`** — Vectorizes each knowledge entry's trigger
  conditions and core knowledge text (TF-IDF, cached to
  `.cache_corpus_vectors.npz`), then matches an observation against that
  vector space. Exposes `retrieve(observation) -> list[dict]`, returning the
  top 3 entries with a `similarity` score.
- **`quality_ranking.py`** — Loads the quality scorecard and computes
  `composite_score = similarity * (pass_count / 8)`, discounting similarity
  by how well-validated an entry is. Assigns `confidence_tier` (`"high"`
  only at a perfect 8/8). Exposes `rank(candidates) -> list[dict]`.
- **`graph_traversal.py`** — Builds a directed graph from the
  complementary-pairs data and walks up to 2 hops forward/backward from a
  matched entry. Flags any neighbor outside the curated 41-entry set rather
  than dropping it silently. Exposes `get_chain_context(entry_id) -> dict`.
- **`response_synthesis.py`** — Combines the top-ranked entry and its chain
  context into a structured response template, then prompts a local LLM
  (via Ollama) to produce a natural-language advisory grounded strictly in
  that data.
- **`main.py`** — Orchestrates `retrieve -> rank -> get_chain_context ->
  synthesize` end to end and exposes it as a CLI.

## Setup

```bash
cd "C:/PROJECTS/DATAPORT"
.venv\Scripts\activate          # or: source .venv/Scripts/activate on Git Bash
pip install numpy networkx
```

Response synthesis requires a local Ollama server:

```bash
ollama serve
ollama pull qwen2.5vl:3b        # or set OLLAMA_MODEL to a model you have
```

## Usage

Run the demo observations through retrieval, ranking, and chain traversal
(no LLM call, fast):

```bash
cd pipeline
python main.py
```

Run a single observation through the full pipeline, including LLM-generated
advisory text:

```bash
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

## Notes

- `embedding_retrieval.py` uses a from-scratch TF-IDF vectorizer rather than
  a transformer embedding model, since no internet-connected embedding
  service is available in this environment. The `retrieve()` contract is
  stable, so the vectorization technique can be upgraded later without
  changing any caller.
- `attackchain_advisor.py` is an earlier, self-contained single-file
  prototype of the same idea (LLM-driven matching instead of TF-IDF
  retrieval) kept for reference; `pipeline/` is the actively maintained,
  modular implementation.
