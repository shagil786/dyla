# Provider Registry Report

**Date:** 2026-09-03
**Status:** Implemented

## Implemented

- Added provider-neutral role settings for model, auditor, embedding, vector store, and web providers.
- Added OpenAI-compatible chat and embedding adapters with `/v1` endpoint normalization, usage parsing, bounded retries, and API-key redaction.
- Added dependency-free local model/embedding/vector choices.
- Added dynamic `module:function` plugin loading for every provider role.
- Added factory composition through `build_provider_bundle`; the CLI now builds all runtime dependencies through the factory.
- Kept You.com exclusively behind `SearchProvider` and retained legacy Azure adapters behind configuration.
- Added tests for settings, endpoint normalization, compatible request shapes, secret redaction, plugin loading, unsupported providers, and bundle composition.
- Updated `.env.example`, README, design spec, and implementation plan.

## Validation

- Focused registry tests: `6 passed`.
- Full offline suite: `124 passed, 1 skipped`.
- The skipped test is the existing explicitly opt-in live Azure Search integration.

## Concerns / follow-up

- Qdrant and FAISS are recognized provider names but currently require an installed adapter/plugin; no optional dependency was added.
- The local model is an explicit offline/smoke-test implementation, not a generative model.
- Legacy Azure settings remain in `Settings` for compatibility; new deployments should select role providers explicitly.
