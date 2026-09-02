# Dyla Research Agent

Dyla is a research agent that will collect and ground answers in evidence.

## Setup

1. Create a virtual environment and install the package with development dependencies:

   ```bash
   python -m venv .venv
   .venv/bin/pip install -e '.[dev]'
   ```

2. Copy `.env.example` to `.env` and replace its fake values with local credentials. Keep `.env` local; it is ignored by Git and must never be committed.

3. Run the test suite:

   ```bash
   .venv/bin/pytest -q
   ```

Configuration is loaded from environment variables or the optional local `.env` file. Provider roles are selected independently with `DYLA_MODEL_PROVIDER`, `DYLA_AUDITOR_PROVIDER`, `DYLA_EMBEDDING_PROVIDER`, `DYLA_VECTOR_STORE`, and `DYLA_WEB_PROVIDER`. The built-in `compatible` adapters speak the standard `/v1/chat/completions` and `/v1/embeddings` APIs and are configured only with endpoint, API key, and model variables. `local` is dependency-free; Azure Search remains available as `azure`, and optional Qdrant/FAISS adapters can be installed or supplied as plugins. You.com is the `SearchProvider` only. Any role can be a custom `module:function` callable receiving `Settings`; secrets stay in the environment and are redacted from adapter errors. Tests use mocked providers and do not make live requests.

## CLI artifacts and evaluation

- `dyla analyst QUESTION` runs only the analyst stage and prints its structured answer.
- `dyla audit TRACE_OR_RUN_ID` reads audit events from a JSONL trace path or from `logs/<run-id>.jsonl`.
- `dyla replay TRACE_OR_RUN_ID` replays either form without model or web calls.
- `dyla evaluate` runs the default eight-question suite and writes `reports/evaluation.json` and `reports/evaluation.md`.
