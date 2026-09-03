# Qdrant Cloud adapter report

## Status

Implemented and verified the configured `DYLA_VECTOR_STORE=qdrant` path.

## Changes

- Added `dyla.qdrant_vector.QdrantVectorStore` using `QDRANT_URL`, `QDRANT_API_KEY`, `QDRANT_COLLECTION`, and `QDRANT_VECTOR_DIMENSIONS`.
- The adapter creates the collection on first use with cosine distance and the configured embedding dimension, while leaving an existing collection unchanged.
- Upserts use `EvidenceChunk` IDs and preserve citation/source URL, title, section, text, position, entity IDs, content hash, and serialized publication date in Qdrant payload metadata.
- Vector search translates entity, source, and publication date constraints into Qdrant payload filters and normalizes scored points into `Evidence`.
- Adapter failures redact the configured Qdrant API key.
- Registered Qdrant in the provider factory. Local storage remains explicit via `DYLA_VECTOR_STORE=local`; FAISS remains an explicit unsupported/plugin path. The Azure Search adapter was not changed.
- Added the `VectorStore` protocol, Qdrant settings, `.env.example` entries, README documentation, `qdrant-client` dependency, and `uv.lock` metadata.

## Tests

- Added mocked-client tests for collection setup, upsert metadata, vector search, metadata filters, missing configuration, and error redaction.
- Focused: `./.venv/bin/python -m pytest -q tests/unit/test_qdrant_vector.py` — 5 passed.
- Full suite: `./.venv/bin/python -m pytest -q` — 129 passed, 1 skipped.
- `git diff --check` passed.

No live Qdrant requests or real credentials were used.
