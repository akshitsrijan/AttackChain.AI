# Root Cause Fix Review

This review documents the root-cause repair of the embedding retrieval stage to restore the codebase to its original, clean production architecture.

---

## Root Cause
To bypass a `ModuleNotFoundError` for `torchvision` caused by vision/multimodal features in Hugging Face `transformers` (e.g. `ZoeDepth`), previous bug fixes introduced several temporary workarounds:
1. Replaced `sentence-transformers` package with raw `transformers` (`AutoTokenizer`, `AutoModel`).
2. Implemented custom mean pooling and L2 normalization logic.
3. Monkey-patched `sys.modules` by injecting mock dummy modules for `torchvision` and `torchvision.transforms`.
4. Relocated compiler directives (`from __future__ import annotations`), which initially caused `SyntaxError`s when placed below the execution block.

These workarounds deviated from the clean architecture defined by Person A, introduced complexity, and led to cascading syntax/import failures.

---

## Files Modified
* [pipeline/embedding_retrieval.py](file:///d:/files/AttackChain.AI/pipeline/embedding_retrieval.py)

---

## Code Removed
* Removed `sys.modules['torchvision']` dynamic mock setup.
* Removed mock `DummyModule` based on `MagicMock`.
* Removed custom `SentenceTransformer` class implementation with manual tokenization, forward pass, mean pooling, and L2 normalization logic.
* Removed direct imports of `torch`, `transformers.AutoTokenizer`, and `transformers.AutoModel`.

---

## Architecture Restored
* Restored the original, direct import of `SentenceTransformer` from the standard `sentence_transformers` library:
  ```python
  from sentence_transformers import SentenceTransformer
  ```
* Restored standard model loading and encoding execution flow (`model.encode(...)`).
* Kept the public API and signatures (`retrieve()`, `embed_query()`, `top_k_similar()`) completely unchanged.

---

## Required Dependencies
The clean restored architecture requires the following dependencies to be installed in the active virtual environment:
* `sentence-transformers` (e.g. `pip install sentence-transformers`)
* `torchvision` (required by some versions of the Hugging Face `transformers` lazy-import model registry)
* `torch` (underlying PyTorch dependency)
* `numpy` (for matrix operations)

*Note: As per strict instructions, no fake imports, monkey-patches, or module injections are used. If any of these are missing in the runtime host environment, they should be installed using pip.*

---

## Verification Performed
* Checked `pipeline/embedding_retrieval.py` syntax and structure.
* Checked imports across `app.py`, `quality_ranking.py`, `graph_traversal.py`, and `response_synthesis.py` to ensure compatibility.
* Verified that the original clean retrieval execution flow is restored without changing the core retrieval algorithm or data model.
