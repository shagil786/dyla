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

Configuration is loaded from environment variables or the optional local `.env` file. Provider roles are selected independently with `DYLA_MODEL_PROVIDER`, `DYLA_AUDITOR_PROVIDER`, `DYLA_EMBEDDING_PROVIDER`, `DYLA_VECTOR_STORE`, and `DYLA_WEB_PROVIDER`. The built-in `compatible` adapters speak the standard `/v1/chat/completions` and `/v1/embeddings` APIs and are configured only with endpoint, API key, and model variables. `local` is dependency-free; Azure Search remains available as `azure`, and Qdrant Cloud is available as `qdrant` when configured with `QDRANT_URL`, `QDRANT_API_KEY`, `QDRANT_COLLECTION`, and `QDRANT_VECTOR_DIMENSIONS`. FAISS remains an explicit plugin/fallback choice rather than a built-in adapter. You.com is the `SearchProvider` only. Any role can be a custom `module:function` callable receiving `Settings`; secrets stay in the environment and are redacted from adapter errors. Tests use mocked providers and do not make live requests.

Reasoning models that emit chain-of-thought prose (for example `<think>...` blocks) in the message content are supported: when the content is not directly valid JSON, the compatible model adapter recovers structured answers via a JSON-extraction fallback (think-block stripping, fenced ```json code blocks, then the first balanced `{...}` object). `DYLA_MODEL_EXTRA_PAYLOAD` and `DYLA_AUDITOR_EXTRA_PAYLOAD` accept JSON objects that are merged into the chat-completions request body; for NVIDIA reasoning endpoints, `{"chat_template_kwargs":{"thinking":false}}` disables thinking so the model emits pure JSON. Empty or unset values leave the payload unchanged. Slow model-based auditors can be given more headroom with `DYLA_AUDITOR_TIMEOUT_SECONDS` (default 10) and `DYLA_AUDITOR_RETRIES` (default 2); the unprefixed `AUDITOR_TIMEOUT_SECONDS` and `AUDITOR_RETRIES` aliases are also accepted.

## CLI artifacts and evaluation

- `dyla analyst QUESTION` runs only the analyst stage and prints its structured answer.
- `dyla audit TRACE_OR_RUN_ID` reads audit events from a JSONL trace path or from `logs/<run-id>.jsonl`.
- `dyla replay TRACE_OR_RUN_ID` replays either form without model or web calls.
- `dyla evaluate` runs the default eight-question suite and writes `reports/evaluation.json` and `reports/evaluation.md`.
