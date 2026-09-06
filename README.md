# Dyla — a research agent that shows its work

Dyla answers open research questions with cited evidence, and a second,
independent agent re-opens every cited source to catch the first one lying.

- **Plans before searching** — expands subqueries, then runs web searches and page fetches in parallel.
- **Cross-checks single-source claims** against an independently fetched page before keeping them.
- **Remembers across questions** — later questions about a known entity reuse earlier evidence and cost less.
- **Refuses to guess** — "insufficient evidence" instead of a plausible fill.
- **Audits itself honestly** — a seeded-defect suite scores the auditor against planted lies, so "approves everything" is measurable.
- **Traces everything** — the plan, every tool call, every course correction, per run, as JSONL.

## Run the evaluation

Two evidence bases, both runnable from this repo.

### 1. Offline replay — no API keys, ~30 seconds

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

**Offline results** (deterministic replay — what the fixtures support):

- 8/8 questions complete; 20/20 seeded defects caught in both modes.
- Memory reuse cuts total tokens 12.5% (including embeddings; model tokens alone −3.9%) and web searches 18 → 5.
- The price: one recall point (16/21 baseline → 15/21 with reuse) — the skipped search would have fetched a Zepto filing.
- Mechanism, and why neither number is 50%: [WRITEUP §3](docs/WRITEUP.md).

### 2. Live — real providers

Configure `.env` — minimum for a live run:

- `DYLA_MODEL_PROVIDER=compatible` with `DYLA_MODEL_BASE_URL`, `DYLA_MODEL_API_KEY`, `DYLA_MODEL_NAME`
- `DYLA_WEB_PROVIDER=you` with `YOU_API_KEY`
- For durable memory: the `DYLA_EMBEDDING_*` set and the `QDRANT_*` set

Then the same suite runs against real search, a real model, and Qdrant:

```bash
# 1. Baseline: memory reuse off, fresh memory database
.venv/bin/python scripts/run_suite.py --live --no-reuse --out reports-live

# 2. Reuse arm: keeps the baseline's memory, so later questions reuse it
.venv/bin/python scripts/run_suite.py --live --out reports-live --keep
```

- Run them in that order: the reuse arm inherits the baseline's memory — the mechanism the comparison measures.
- Output: `runs/live-no-reuse/`, `runs/live-reuse/`, `reports-live/`. Keep `--out reports-live` — the default `reports/` is the committed offline evidence.
- Each question has a hard 120-second wall-clock ceiling; a full suite takes 6–8 minutes and roughly ₹0.6 in projected model tokens, plus You.com and embedding usage. The seeded-defect audit runs live at the end.
- `--fresh` (the default) wipes `dyla.db` and `logs/` at the start; `--keep` retains prior memory — that is what lets the reuse arm build on the baseline.

**Live results** (committed from exactly the commands above):

- Web searches 15 → 9; pages fetched 73 → 32.
- Subqueries skipped by reuse: 0 → 18, climbing question by question as memory fills.
- Wall time *falls* with reuse (Q8: 82s → 29s) while the baseline's climbs.
- Accuracy holds: 5/8 complete vs 4/8; seeded audit 15/20 vs 14/20.
- Two defects found live that the offline suite structurally could not see — a missing Qdrant index, and live mode never creating entities. Both fixed, both written up.

**Read [`docs/WRITEUP.md`](docs/WRITEUP.md) first.** It states up front what
each evidence base is and exactly which conclusions each does and does not
support.

## Ask it a question

With the live configuration from above in `.env`:

```bash
dyla ask "What is the current GST rate applied to restaurant services in India?"
```

This runs the full pipeline: plan → web search → page fetch → cited answer →
independent audit → memory → trace. Real output from that run:

```text
The GST rate applied to restaurant services in India varies based on the type
of restaurant and its location. For regular restaurants ...
Citations: 3
Verdicts: 3
Status: complete
Run: dfe2657ee0c44e9f9b3971f80f0f20cf
Trace: logs/dfe2657ee0c44e9f9b3971f80f0f20cf.jsonl
```

Run status:

- `complete` — every claim audited, no issues.
- `incomplete` — the auditor flagged issues (an unsupported claim, for example); the answer is preserved and the findings reported.
- `unaudited` — no claims survived to audit, or the auditor could not run; the trace says which.

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
