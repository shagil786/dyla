# Dyla — a research agent that shows its work

Dyla answers open research questions by planning subqueries, searching the
live web, fetching pages, and synthesising a cited answer — then a second,
independent agent re-opens every cited source and tries to catch the first one
lying. It cross-checks claims that appear in only one source, carries what it
learns across questions so later questions about the same entity cost less,
and says "insufficient evidence" instead of guessing. Every run writes a full
JSONL trace: the plan, every tool call, what came back, and every course
correction.

## Run the evaluation (30 seconds, no API keys)

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python scripts/run_suite.py
```

This runs the eight-question suite against a recorded fixture corpus and
writes:

| Artifact | Contents |
| --- | --- |
| `runs/reuse/qNN-*.jsonl` | Full log per question: plan, every tool call, every result, every course correction |
| `reports/evaluation.md` | Cost per question in tokens and projected rupees (priced at `gpt-4o-mini` list rates; the offline model's own rupee column reads `unpriced` — no price is invented), plus the trend across the suite and an answer-completeness score (`src/dyla/recall.py`) |
| `reports/auditor-findings.md` | What the auditor caught, including a seeded-defect audit of the auditor itself |
| `reports/run-summary.json` | Machine-readable totals |

The questions are `DEFAULT_QUESTIONS` in `src/dyla/evaluation.py`; the
planted defects the auditor is scored against are in `src/dyla/findings.py`.

Run the baseline for the memory comparison:

```bash
.venv/bin/python scripts/run_suite.py --no-reuse   # writes runs/no-reuse/ and reports/*-no-reuse.*
```

**Offline results** (deterministic replay, what the fixtures support):
8/8 questions complete, 20/20 seeded defects caught in both modes. Memory
reuse cuts total tokens 12.5% (including embedding tokens; model tokens alone
−3.9%), web searches 18 → 5, and costs one recall point (16/21 baseline,
15/21 with reuse) because one skipped search would have fetched a Zepto
filing. The saving is real and so is the price — [WRITEUP §3](docs/WRITEUP.md)
explains the mechanism and why neither number is 50%.

**Live results** (real web search, real model, real Qdrant — committed in
`reports-live/` and `runs/live-*/`): memory reuse cut web searches 15 → 9 and
pages fetched 73 → 32, with per-question wall time *falling* (Q8: 82s → 29s)
while the baseline's climbs, and accuracy holding. The live runs also found
two defects the offline suite structurally could not (a missing Qdrant index,
and live mode never creating entities) — both fixed, both written up.

**Read [`docs/WRITEUP.md`](docs/WRITEUP.md) first.** It states up front what
each evidence base is and exactly which conclusions each does and does not
support.

## Ask it a question

Configure `.env` (see Setup), then:

This runs the full pipeline: plan → web search → page fetch → cited answer →
independent audit → memory → trace. Real output from a live run:

```bash
dyla ask "What is the current GST rate applied to restaurant services in India?"
```

```text
The GST rate applied to restaurant services in India varies based on the type
of restaurant and its location. For regular restaurants ...
Citations: 3
Verdicts: 3
Status: complete
Run: dfe2657ee0c44e9f9b3971f80f0f20cf
Trace: logs/dfe2657ee0c44e9f9b3971f80f0f20cf.jsonl
```

Minimum live configuration in `.env`: `DYLA_MODEL_PROVIDER=compatible` plus
`DYLA_MODEL_BASE_URL`, `DYLA_MODEL_API_KEY`, `DYLA_MODEL_NAME`, and
`DYLA_WEB_PROVIDER=you` plus `YOU_API_KEY`. Auditing with a model instead of
the deterministic local auditor adds the `DYLA_AUDITOR_*` set; durable memory
adds `DYLA_EMBEDDING_*` and the `QDRANT_*` set (`.env.example` documents all
of them).

Status meanings: `complete` — every claim audited, no issues. `incomplete` —
the auditor flagged issues (an unsupported claim, for example); the answer is
preserved and the findings reported. `unaudited` — no claims survived to
audit, or the auditor could not run; the trace says which.

Other commands:

```bash
dyla analyst "question"     # analyst stage only, no audit (debugging)
dyla audit <run-id>         # audit verdicts for a past run
dyla replay <run-id>        # re-read a trace with zero API calls
dyla memory list            # inspect accumulated research memory
dyla evaluate               # the eight-question suite (live: costs money)
dyla evaluate --questions-file questions.txt   # custom suite
dyla ask --json "question"  # machine-readable output
```

`ask` is one question and the cheapest live test; the unit-test suite makes no
API calls at all.

## Setup

1. Create a virtual environment and install with development dependencies:

   ```bash
   python -m venv .venv
   .venv/bin/pip install -e '.[dev]'
   ```

2. Copy `.env.example` to `.env` and fill in credentials. Keep `.env` local —
   it is gitignored and must never be committed.

3. Run the tests:

   ```bash
   .venv/bin/pytest -q
   ```

### Providers

Each role is selected independently and defaults to the dependency-free
`local` adapter, so a fresh checkout runs with no credentials:

| Role | Variable | Values |
| --- | --- | --- |
| Model | `DYLA_MODEL_PROVIDER` | `local` (default), `compatible` |
| Auditor | `DYLA_AUDITOR_PROVIDER` | `local` (default), `compatible` |
| Embeddings | `DYLA_EMBEDDING_PROVIDER` | `local` (default), `compatible` |
| Vector store | `DYLA_VECTOR_STORE` | `local` (default), `qdrant` |
| Web search | `DYLA_WEB_PROVIDER` | `unconfigured` (default), `you` |

The `compatible` adapters speak the standard `/v1/chat/completions` and
`/v1/embeddings` APIs — any OpenAI-compatible endpoint works, configured only
with base URL, API key, and model variables (`.env.example` documents every
variable). Qdrant Cloud needs `QDRANT_URL`, `QDRANT_API_KEY`,
`QDRANT_COLLECTION`, and `QDRANT_VECTOR_DIMENSIONS`. Any role can instead be a
custom `module:function` callable receiving `Settings`; secrets stay in the
environment and are redacted from adapter errors. (The removed Azure adapters
and the FAISS plugin option are covered in WRITEUP §0.)

Two behaviours worth knowing:

- **Reasoning models.** If the model emits `<think>…</think>` prose, the
  adapter recovers the structured answer via JSON-extraction fallbacks. For
  NVIDIA reasoning endpoints, `DYLA_MODEL_EXTRA_PAYLOAD={"chat_template_kwargs":{"thinking":false}}`
  disables thinking so the model emits pure JSON.
- **Slow auditors.** `DYLA_AUDITOR_TIMEOUT_SECONDS` (default 10) and
  `DYLA_AUDITOR_RETRIES` (default 2) give model-based auditors headroom.

### Optional: a global `dyla` command

```bash
mkdir -p ~/.local/bin
cat > ~/.local/bin/dyla <<'EOF'
#!/bin/zsh
DYLA_HOME="$HOME/code/projects/dyla"  # adjust to your checkout
cd "$DYLA_HOME"
exec "$DYLA_HOME/.venv/bin/dyla" "$@"
EOF
chmod +x ~/.local/bin/dyla
```

The launcher changes into the project directory first, so the local `.env` is
loaded from anywhere. Without it, run `.venv/bin/dyla ...` from inside the
project.

## Where to read more

- [`docs/WRITEUP.md`](docs/WRITEUP.md) — why it is built this way, what was
  tried and rejected, and the named weaknesses. Carries the most weight.
- [`docs/FIX_BACKLOG.md`](docs/FIX_BACKLOG.md) — every finding from every
  review, reconciled against measurements.
- [`reports/`](reports/) and [`runs/`](runs/) — the offline evidence base;
  `reports-live/` and `runs/live-*/` — the live runs.
