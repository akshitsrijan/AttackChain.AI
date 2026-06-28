# AttackChain Advisor

An AI-powered reasoning assistant that takes a security researcher's
free-text observation, retrieves the most relevant entry from a curated
offensive-security knowledge base, weighs it against a quality scorecard,
traces the attack chain it belongs to, and synthesizes a grounded advisory
response.

This repository keeps each working snapshot of the project in its own
versioned subfolder (`0.0.1`, `0.0.2`, `0.0.3`, ...) rather than overwriting
history in place. **`0.0.3` is the current/latest version** — start there
unless you specifically need an older snapshot.

## Version history

### 0.0.1 — initial pipeline
The first working version of the four-stage pipeline, laid out under
`knowledge_graph_processing/`:
- `embedding_retrieval.py` — TF-IDF similarity search (no external model).
- `quality_ranking.py` — quality-adjusted re-scoring.
- `graph_traversal.py` — cross-reference graph traversal.
- `response_synthesis.py` — response template + LLM call (Ollama).
- `main.py` — CLI orchestrator wiring the four stages together.

### 0.0.2 — semantic retrieval, Gemini synthesis, Streamlit UI
A substantial rework, moved into a `pipeline/` folder:
- **Retrieval** (`embedding_retrieval.py`) upgraded from TF-IDF to real
  sentence embeddings (`sentence-transformers/all-MiniLM-L6-v2`) with a
  cross-encoder reranking pass (`cross-encoder/ms-marco-MiniLM-L-6-v2`) for
  finer relevance judgement. Corpus embeddings are cached to disk and
  auto-invalidated via an MD5 fingerprint of the corpus text.
- **Response synthesis** (`response_synthesis.py`) switched from a local
  Ollama call to the **Gemini API** (`GEMINI_API_KEY`), adding an intent
  extraction step and a consistency-validation step before generation, with
  a local template fallback when no API key is set or the call fails.
  Exposes a single `analyze(observation)` entry point that runs the whole
  pipeline (intent → retrieval → ranking → traversal → validation →
  generation) and returns one structured result dict.
- **`app.py`** — a Streamlit dashboard (`streamlit run app.py`) visualizing
  every stage of the pipeline: matched entry, confidence tier, attack chain
  graph, execution time, and which LLM/fallback path was used.
- **`run_benchmark.py` / `verify_retrieval.py`** — retrieval accuracy
  benchmarking and verification scripts.
- A set of `*_Review.md` documents recording the design rationale and
  before/after analysis for each stage (`Embedding_Retrieval_Review.md`,
  `Quality_Ranking_Review.md`, `Graph_Traversal_Review.md`,
  `Response_Synthesis_Review.md`, `Streamlit_UI_Review.md`,
  `Retrieval_Benchmark.md`, `Retrieval_Enhancement_Review.md`,
  `Bug_Fix_Review.md`, `Root_Cause_Fix_Review.md`,
  `Future_Import_Fix_Review.md`) — read these if you want the "why" behind
  a specific stage's current implementation.

### 0.0.3 — Ollama synthesis
Started as an exact snapshot of `0.0.2`, then switched response synthesis
back from the Gemini API to a local **Ollama** call (`qwen2.5vl:3b` by
default, configurable via `OLLAMA_HOST`/`OLLAMA_MODEL`). Same retrieval,
ranking, traversal, and validation stages as `0.0.2`; only the LLM backend
in `response_synthesis.py` differs — no API key needed, but requires
`ollama serve` running locally with the model pulled.

## Datasets

All three source datasets live under `experimental data/experimental data/`
inside each version folder, and are explained in detail in `instructions.md`:

- **`experiential_knowledge_41.json`** — 41 structured offensive-security
  knowledge entries (trigger conditions, abstracted IF/THEN patterns,
  pitfalls, confidence, shelf-life).
- **`quality_metrics.json`** — an 8-point quality scorecard per entry (e.g.
  does the trigger describe a situation rather than an action, is a pitfall
  present, is confidence justified).
- **`cross_references.json`** — a directed graph of complementary entry
  pairs and suggested multi-step attack chains, extending beyond the 41
  curated entries to `ek_0253`.

## How the pipeline works (0.0.2 / 0.0.3)

```
Researcher observation
        |
        v
Intent Extraction      -> (LLM, optional) distills a noisy observation
                           into a concise security intent
        |
        v
Embedding Retrieval     -> sentence-embedding similarity search + cross-encoder
                            rerank -> top candidate knowledge entries
        |
        v
Quality Ranking         -> re-scores candidates by similarity x quality,
                            assigns a confidence tier
        |
        v
Graph Traversal         -> follows the cross-reference graph from the top
                            entry to find next/previous steps in the chain
        |
        v
Consistency Validation  -> checks the matched entry/chain against the
                            original observation before generating text
        |
        v
Response Generation     -> LLM generates the advisory grounded in the above
                            (Gemini API in 0.0.2, local Ollama in 0.0.3);
                            falls back to a local template if the LLM is
                            unavailable or the call fails
```

## Quickstart (0.0.3 — latest version)

### 1. Requirements
- Python 3.10+
- A local Ollama server with `qwen2.5vl:3b` pulled (optional but
  recommended — without it, the system falls back to a local templated
  response instead of LLM-generated text)

### 2. Set up the environment
```bash
cd "AttackChain.AI/0.0.3"
python -m venv .venv
source .venv/Scripts/activate        # Windows Git Bash
# .venv\Scripts\activate.bat         # Windows cmd
# source .venv/bin/activate          # macOS/Linux

pip install sentence-transformers numpy networkx pandas plotly streamlit matplotlib
```

The first run will download the embedding model
(`all-MiniLM-L6-v2`) and cross-encoder model
(`ms-marco-MiniLM-L-6-v2`) from Hugging Face — this requires an internet
connection once; they're cached locally afterward.

### 3. (Optional) Start Ollama for LLM-generated responses
```bash
ollama serve
ollama pull qwen2.5vl:3b        # or set OLLAMA_MODEL to a model you have
```
If `ollama serve` isn't running, the pipeline still runs end-to-end and
produces a locally-templated advisory instead of an LLM-generated one —
useful for testing without Ollama installed.

### 4. Run the pipeline
From inside `0.0.3/pipeline/`:
```bash
cd pipeline
python main.py "I noticed CRLF sequences are tolerated inside a gopher:// URI without rejection"
```
This prints the matched knowledge entry, its confidence tier, the attack
chain, and the generated (or fallback) advisory text.

### 5. Run the Streamlit dashboard
From `0.0.3/`:
```bash
streamlit run app.py
```
Opens a browser dashboard where you can type an observation and see every
pipeline stage's output (matched entry, confidence tier, chain graph,
execution time, and which model/fallback path answered).

### 6. Run the test suite / benchmarks
```bash
python test_pipeline_combination.py    # fixture-based combination tests
python verify_retrieval.py             # retrieval sanity checks
python run_benchmark.py                # retrieval accuracy benchmark
```

## Quickstart (0.0.1 — original TF-IDF version)

No external models or API key required — useful as a lightweight reference
implementation.

```bash
cd "AttackChain.AI/0.0.1"
pip install numpy networkx
cd knowledge_graph_processing
python main.py "your observation here"
```
Requires a local Ollama server (`ollama serve`, with a model such as
`qwen2.5vl:3b` pulled) for LLM-generated text; otherwise only structured
retrieval/ranking/chain output is produced.

## Notes

- Each version folder is self-contained — install dependencies and run
  commands from inside the specific version you intend to use, not from
  the repository root.
- `0.0.2` and `0.0.3` share the same retrieval/ranking/traversal/validation
  stages; they differ only in `response_synthesis.py`'s LLM backend
  (Gemini API vs. local Ollama). `0.0.3` is the recommended starting point
  for any new work.
