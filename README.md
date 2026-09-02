# Dyla Research Agent

Dyla is a research agent that will collect and ground answers in evidence.

## Setup

1. Create a virtual environment and install the package with development dependencies:

   ```bash
   python -m venv .venv
   .venv/bin/pip install -e '.[dev]'
   ```

2. Copy `.env.example` to `.env` and replace its fake values with credentials from your local Azure and You.com resources. Keep `.env` local; it is ignored by Git and must never be committed.

3. Run the test suite:

   ```bash
   .venv/bin/pytest -q
   ```

Configuration is loaded from environment variables or the optional local `.env` file. `DYLA_WEB_PROVIDER=you` selects You.com for search and page retrieval only; Azure AI Search remains the vector-store adapter. Required model, web-provider, and Azure AI Search settings are validated when `load_settings()` is called. Tests use mocked providers and do not make live requests.

## CLI artifacts and evaluation

- `dyla analyst QUESTION` runs only the analyst stage and prints its structured answer.
- `dyla audit TRACE_OR_RUN_ID` reads audit events from a JSONL trace path or from `logs/<run-id>.jsonl`.
- `dyla replay TRACE_OR_RUN_ID` replays either form without model or web calls.
- `dyla evaluate` runs the default eight-question suite and writes `reports/evaluation.json` and `reports/evaluation.md`.
