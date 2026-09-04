# Dyla Research Agent

Dyla is a research agent that will collect and ground answers in evidence.

## Reproduce the evaluation in one command

No API keys, no configuration, ~0.3 seconds:

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python scripts/run_suite.py
```

This runs the full eight-question suite against a recorded fixture corpus and
writes:

| Artifact | Contents |
| --- | --- |
| `runs/reuse/qNN-*.jsonl` | Full log per question: plan, every tool call, every result, every course correction |
| `reports/evaluation.md` | Cost per question in tokens and rupees, plus the trend across the eight questions |
| `reports/auditor-findings.md` | What the auditor caught, including a seeded-defect audit of the auditor itself |
| `reports/run-summary.json` | Machine-readable totals |

To reproduce the memory-transfer comparison, run the baseline too:

```bash
.venv/bin/python scripts/run_suite.py --no-reuse   # writes runs/no-reuse/ and reports/*-no-reuse.*
```

**Read [`docs/WRITEUP.md`](docs/WRITEUP.md) first.** It states up front that
these results are a deterministic replay of recorded pages, not a live LLM run,
and explains exactly which conclusions that does and does not support.

To run against real providers instead, configure `.env` (see Setup) and pass
`--live`.

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

### Optional: a global `dyla` command

Create a launcher so `dyla` works from any directory (adjust `DYLA_HOME` if the project lives elsewhere; `~/.local/bin` must be on your `PATH`):

```bash
mkdir -p ~/.local/bin
cat > ~/.local/bin/dyla <<'EOF'
#!/bin/zsh
DYLA_HOME="$HOME/code/projects/dyla"
cd "$DYLA_HOME"
exec "$DYLA_HOME/.venv/bin/dyla" "$@"
EOF
chmod +x ~/.local/bin/dyla
```

The launcher changes into the project directory first, so the local `.env` is loaded no matter where you run the command. Without it, run `.venv/bin/dyla ...` from inside the project directory instead.

## Usage

### Ask a research question (main command)

```bash
dyla ask "What is the capital of Australia?"
```

This runs the full pipeline: web search → evidence extraction → model answer with citations → independent model auditor → memory update → trace. Example output:

```text
Canberra
Citations: 2
Verdicts: 2
Status: complete
Run: 5bb107afa93e47d7b214eb4f9714e58c
Trace: logs/5bb107afa93e47d7b214eb4f9714e58c.jsonl
```

Ask anything real:

```bash
dyla ask "Which three Indian jewellery retailers opened the most new stores in the last two years?"
```

### Other commands

```bash
dyla analyst "question"      # analyst answer only, no audit stage (faster debugging)
dyla audit <run-id>          # show audit verdicts for a past run
dyla replay <run-id>         # re-examine a run with zero API calls (free)
dyla memory list             # inspect accumulated research memory
dyla evaluate                # full eight-question suite (makes many live API calls)
dyla evaluate --questions-file questions.txt  # run a custom suite instead (one question per line)
dyla ask --json "question"   # machine-readable output
```

### Interpreting run status

- `complete` — every claim was audited and no issues were found.
- `incomplete` — the auditor flagged issues (for example an unsupported claim); the original answer is preserved and the findings are reported.
- `unaudited` — the auditor could not run; see the run trace under `logs/` for the reason.

Every run's full detail is in its JSONL trace under `logs/`; `dyla replay` re-reads a trace without any model or web calls.

### Cost notes

`ask` is a single question (search + a few model calls) and is the cheapest way to test. `evaluate` runs eight full pipelines and costs correspondingly more. The unit test suite makes no API calls at all.

## CLI artifacts and evaluation

- `dyla ask QUESTION` runs the complete analyst → audit → memory → trace → quality flow.
- `dyla analyst QUESTION` runs only the analyst stage and prints its structured answer.
- `dyla audit TRACE_OR_RUN_ID` reads audit events from a JSONL trace path or from `logs/<run-id>.jsonl`.
- `dyla replay TRACE_OR_RUN_ID` replays either form without model or web calls.
- `dyla memory list` inspects durable research memory.
- `dyla evaluate` runs the default eight-question suite and writes `reports/evaluation.json` and `reports/evaluation.md`. Pass `--questions-file PATH` (one question per line, blank lines ignored) to run a custom suite instead. Both reports include a per-question cost table (tokens, estimated cost in adapter units, duration, memory hits) with totals, and the Markdown report adds a cost-trend note showing how cost and memory hits evolved across the suite.
