# Task 5 Report: Web tools, normalization, chunking, and Azure AI Search

## Status

Implemented Task 5 from the brief. No real Azure credentials or live services were used.

## Tests and exact output

Focused TDD RED checks:

- `.venv/bin/pytest -q tests/unit/test_web.py tests/unit/test_chunking.py tests/unit/test_search.py tests/integration/test_azure_search.py`
  - Initial result: collection errors because `dyla.web`, `dyla.chunking`, and `dyla.search` did not yet exist.
- `.venv/bin/pytest -q tests/unit/test_ingest.py`
  - Initial result: collection error because `dyla.ingest` did not yet exist.
- `.venv/bin/pytest -q tests/unit/test_search.py::test_search_index_can_embed_chunks_when_vectors_are_not_supplied`
  - Initial result: 1 expected failure because `SearchIndex` did not yet accept an injected embedder.

Focused GREEN result after implementation:

```text
...........s                                                                                 [100%]
11 passed, 1 skipped in 0.09s
```

Full suite result:

```text
s......................................................                                      [100%]
54 passed, 1 skipped in 0.22s
```

The one skipped test is `tests/integration/test_azure_search.py`, gated by `DYLA_RUN_LIVE_TESTS=1`.

Diagnostics were also run on each changed production module. `search.py`, `chunking.py`, `ingest.py`, and `domain.py` have no diagnostics. The web import-order warning was fixed; the remaining project diagnostic is the pre-existing analyzer warning on `AuditVerdict.status` in `domain.py`.

## Files changed

- `src/dyla/web.py`
  - Added HTTPS-only external URL validation.
  - Rejects local, loopback, private, link-local, reserved, `.local`, and credential-bearing URLs.
  - Added `PageFetcher` with response size/content-type checks, redirect-target validation, HTML normalization, title extraction, boilerplate removal, and deterministic source IDs.
  - Added `WebSearcher` Bing-compatible adapter returning `SearchHit` contracts.
- `src/dyla/chunking.py`
  - Added deterministic heading/paragraph-aware chunking.
  - Supports bounded chunk sizes and overlap.
  - Preserves URL, title, source ID, section, position, entity IDs, publication date, content hash, and deterministic chunk ID.
- `src/dyla/search.py`
  - Added Azure AI Search REST adapter.
  - Creates a vector-enabled index schema using configured vector dimensions.
  - Supports batched merge-or-upload operations.
  - Supports injected embedding models for `upsert(chunks)` as well as explicitly supplied vectors.
  - Performs keyword plus vector hybrid search with entity/source/date OData filters.
- `src/dyla/ingest.py`
  - Added fetch-independent embedding ingestion orchestration: chunk, embed, validate vector count, and upsert.
- `src/dyla/domain.py`
  - Added optional `published_at` to `EvidenceChunk` to preserve citation/date metadata without breaking earlier constructors.
- `src/dyla/config.py`
  - Added `azure_search_vector_dimensions` with a backward-compatible default of `1536`.
- `tests/unit/test_web.py`
- `tests/unit/test_chunking.py`
- `tests/unit/test_search.py`
- `tests/unit/test_ingest.py`
- `tests/integration/test_azure_search.py`

## Decisions

1. Used Azure AI Search REST endpoints rather than adding the Azure Search SDK dependency; this keeps the package dependency-light and makes mocked transport tests deterministic.
2. Used the existing `AzureEmbeddingModel` through a small protocol/injection boundary rather than duplicating embedding HTTP or cache logic.
3. Made vector dimensions configuration-driven with a default of 1536 for compatibility with existing settings construction.
4. Kept `chunk_document` strict about invalid overlap limits, while ingestion clamps its convenience default when a caller intentionally chooses a small `max_chars`.
5. Used standard-library `HTMLParser` and conservative block filtering instead of adding BeautifulSoup or another parser dependency.
6. Kept the live Azure test explicitly opt-in and skipped by default so ordinary tests never require credentials or network access.

## Concerns and follow-up

- The live integration test is an explicit opt-in smoke-test gate but is intentionally not run in this environment because no real credentials are available. A deployment environment should add a credentialed live test body if live schema/retrieval verification is required.
- `PageFetcher` enforces the configured limit after the HTTP response has been received. This bounds retained/parsed content but is not a streaming network-level download cap; a future hardening pass could use streaming reads.
- Web search is implemented against the Bing Web Search v7-compatible response shape. If the deployment uses a different provider, its endpoint/field mapping should be configured or adapted.
- The analyzer still reports the existing `AuditVerdict.status` diagnostic; it is unrelated to Task 5 and does not affect the pytest suite.

## Review-fix report — 2026-09-02

### Findings fixed

1. Disabled automatic redirects in `PageFetcher`; each `Location` target is resolved and validated before following, with a configurable redirect limit.
2. Added DNS resolution checks for every URL host, rejecting IPv4/IPv6 private, loopback, link-local, reserved, unspecified, and unresolved destinations. The practical limitation is documented in `web.py`: a standard httpx transport can resolve again after preflight, leaving a theoretical DNS rebinding/TOCTOU window; eliminating it requires a custom pinned-address transport with correct TLS SNI/certificate handling.
3. Corrected Azure AI Search hybrid payload from `search_text` to `search`, with an exact decoded JSON assertion.
4. Added early `Content-Length` rejection and incremental streaming byte accounting, avoiding response buffering beyond the configured limit.
5. Replaced the fake live assertion with an opt-in smoke test that creates a UUID-suffixed index, upserts a vector document, performs hybrid retrieval with entity/source filters, verifies the document, and deletes the index in `finally`.
6. Reworked oversized paragraph splitting into lossless overlapping windows and added a regression test that checks every source token survives.
7. Validated the configured web search endpoint at construction and validated/skipped insecure or unsafe result URLs before they enter the fetch pipeline.
8. Added focused redirect, redirect-limit, DNS/private-resolution, streaming-size, early Content-Length, and malformed-date tests.

### Fix TDD and verification output

RED reproduction:

```text
...F............s                                                                            [100%]
1 failed, 15 passed, 1 skipped in 0.13s
```

The failure was the expected pre-fix redirect test: the old implementation followed the private redirect through automatic httpx redirects.

Focused final command:

```text
.venv/bin/pytest -q tests/unit/test_web.py tests/unit/test_chunking.py tests/unit/test_search.py tests/unit/test_ingest.py tests/integration/test_azure_search.py
```

Output:

```text
..................s                                                                          [100%]
18 passed, 1 skipped in 0.10s
```

Full final command:

```text
.venv/bin/pytest -q
```

Output:

```text
s.............................................................                               [100%]
61 passed, 1 skipped in 0.15s
```

`git diff --check` completed without output. Changed production modules have no diagnostics after the import cleanup; the existing unrelated `AuditVerdict.status` analyzer diagnostic remains documented above.

### Fix concerns

- The live test is real and cleanup-safe, but it was not run here because no Azure credentials were available; default CI remains credential-free and skips it.
- DNS preflight substantially reduces SSRF/rebinding risk but cannot fully pin the address with the current standard httpx transport abstraction. The limitation is documented in code and this report.
- Search result URLs that fail safety validation are skipped rather than fetched; callers should monitor skipped-result counts if provider data quality matters.

## Re-review fix report — 2026-09-02

### Findings addressed

1. Added explicit hostname-resolution regression coverage for IPv6 loopback (`::1`), link-local (`fe80::1`), private (`fc00::1`), documentation/reserved (`2001:db8::1`), unspecified (`::`), and multicast (`ff02::1`) destinations.
2. Added coverage for IPv4 CGNAT (`100.64.0.1`) and multicast (`224.0.0.1`), plus legitimate public IPv4 (`93.184.216.34`) and IPv6 (`2606:4700:4700::1111`) acceptance.
3. Updated the external destination predicate to reject multicast and all addresses for which `ipaddress` reports `is_global == False`; this covers non-public CGNAT and other non-routable ranges without rejecting the tested public addresses.
4. Kept the DNS rebinding/TOCTOU limitation explicit in `src/dyla/web.py` and the prior report. Standard httpx preflight validation does not fully pin the address used by the later connection.

### Exact verification

RED command:

```text
.venv/bin/pytest -q tests/unit/test_web.py -k 'hostname_resolution'
```

RED output:

```text
.....FFF.                                                                                    [100%]
6 passed, 3 failed, 9 deselected in 0.11s
```

GREEN focused command:

```text
.venv/bin/pytest -q tests/unit/test_web.py -k 'hostname_resolution'
```

GREEN output:

```text
.........                                                                                    [100%]
9 passed, 9 deselected in 0.09s
```

Task 5 focused command:

```text
.venv/bin/pytest -q tests/unit/test_web.py tests/unit/test_chunking.py tests/unit/test_search.py tests/unit/test_ingest.py tests/integration/test_azure_search.py
```

Output:

```text
...........................s                                                                 [100%]
27 passed, 1 skipped in 0.26s
```

Full command:

```text
.venv/bin/pytest -q
```

Output:

```text
s......................................................................                      [100%]
70 passed, 1 skipped in 0.46s
```

`src/dyla/web.py` diagnostics: no errors or warnings.

### Remaining concern

The DNS resolution check rejects all non-global and multicast destinations before requests, but the default httpx transport may perform a second DNS lookup during connection establishment. Fully eliminating the remaining rebinding/TOCTOU window would require a custom transport that pins the validated address while retaining correct HTTPS SNI and certificate verification; this fix does not claim to provide that.
