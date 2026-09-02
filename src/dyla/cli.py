"""Typer command line interface for Dyla research runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from .analyst import AnalystAgent
from .auditor import AuditorAgent

from .config import Settings, load_settings
from .entities import EntityResolver
from .evaluation import run_evaluation
from .memory import MemoryStore
from .orchestrator import RunOrchestrator, RunResult
from .provider_factory import (
    build_auditor_provider,
    build_embedding_provider,
    build_model_provider,
    build_search_provider,
    build_vector_store,
)
from .tracing import TraceWriter

app = typer.Typer(help="Research questions with cited, independently audited evidence.")
memory_app = typer.Typer(help="Inspect durable research memory.")
app.add_typer(memory_app, name="memory")


def _build_memory(settings: Settings) -> MemoryStore:
    del settings
    store = MemoryStore()
    store.initialize()
    return store


def _build_analyst(settings: Settings) -> AnalystAgent:
    memory = _build_memory(settings)
    provider = build_search_provider(settings)
    model = build_model_provider(settings)
    embedder = build_embedding_provider(settings, cache_path="dyla.db")
    index = build_vector_store(settings, embedder=embedder)
    return AnalystAgent(
        model=model, resolver=EntityResolver(memory), memory=memory,
        searcher=provider, fetcher=provider, index=index, embedder=embedder,
        trace_writer=TraceWriter(),
    )


def _build_orchestrator(settings: Settings) -> RunOrchestrator:
    analyst = _build_analyst(settings)
    return RunOrchestrator(
        analyst=analyst,
        auditor=AuditorAgent(fetcher=analyst.fetcher, comparator=build_auditor_provider(settings), trace_writer=TraceWriter()),
        memory=analyst.memory,
        trace_writer=TraceWriter(),
    )


def _resolve_trace(value: str) -> Path:
    candidate = Path(value).expanduser()
    if candidate.is_file():
        return candidate
    run_path = Path("logs") / f"{value}.jsonl"
    if run_path.is_file():
        return run_path
    raise typer.BadParameter(f"run trace not found: {value}")


def _read_trace(value: str) -> tuple[Path, list[dict[str, Any]]]:
    path = _resolve_trace(value)
    try:
        events = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            if not isinstance(event, dict):
                raise typer.BadParameter(f"invalid trace artifact: {path}; each JSONL event must be a JSON object")
            events.append(event)
    except (OSError, json.JSONDecodeError) as exc:
        raise typer.BadParameter(f"invalid trace artifact: {path}") from exc
    return path, events


def _print_result(result: RunResult, json_output: bool) -> None:
    payload = {
        "run_id": result.run_id,
        "answer": result.answer.model_dump(mode="json"),
        "verdicts": [item.model_dump(mode="json") for item in result.verdicts],
        "quality": {"status": result.quality.status, "issues": result.quality.issues},
        "metrics": result.metrics.model_dump(mode="json"),
        "trace_path": str(result.trace_path),
    }
    if json_output:
        typer.echo(json.dumps(payload, indent=2, default=str))
        return
    typer.echo(result.answer.answer)
    typer.echo(f"Citations: {sum(len(claim.citations) for claim in result.answer.claims)}")
    typer.echo(f"Verdicts: {len(result.verdicts)}")
    typer.echo(f"Status: {result.quality.status}")
    typer.echo(f"Run: {result.run_id}")
    typer.echo(f"Trace: {result.trace_path}")


@app.command()
def ask(question: str, json_output: bool = typer.Option(False, "--json")) -> None:
    """Run the complete analyst → audit → memory → trace → quality flow."""
    result = __import__("asyncio").run(_build_orchestrator(load_settings()).ask(question))
    _print_result(result, json_output)


@app.command()
def analyst(question: str, json_output: bool = typer.Option(False, "--json")) -> None:
    """Run the analyst stage and print its structured answer."""
    analyst = _build_analyst(load_settings())
    run_id = __import__("uuid").uuid4().hex
    answer = __import__("asyncio").run(analyst.run(question, run_id))
    data: Any = answer.model_dump(mode="json") if json_output else answer.answer
    typer.echo(json.dumps(data, indent=2) if json_output else data)


@app.command()
def audit(artifact: str, json_output: bool = typer.Option(False, "--json")) -> None:
    """Show audit verdicts from a trace artifact or run ID."""
    _path, events = _read_trace(artifact)
    verdicts = [event for event in events if event.get("event") == "claim_audited"]
    typer.echo(json.dumps(verdicts, indent=2) if json_output else f"Verdicts: {len(verdicts)}")


@app.command()
def evaluate(json_output: bool = typer.Option(False, "--json")) -> None:
    """Run the default question suite and write reports/evaluation.{json,md}."""
    payload = run_evaluation()
    typer.echo(json.dumps(payload, indent=2) if json_output else f"Evaluated {payload['total']} questions; {payload['passed']} passed")


@memory_app.command("list")
def memory_list(query: str = typer.Option("", "--query"), limit: int = typer.Option(10, "--limit")) -> None:
    """List matching durable memory records."""
    store = _build_memory(load_settings())
    records = store.search_memory(query, limit) if query else []
    if not records:
        typer.echo("No memory records")
        return
    for record in records:
        typer.echo(f"{record.kind}: {record.text}")


@app.command()
def replay(artifact: str, json_output: bool = typer.Option(False, "--json")) -> None:
    """Replay a trace artifact or run ID without making model or web calls."""
    path, events = _read_trace(artifact)
    typer.echo(json.dumps(events, indent=2) if json_output else f"Replayed {len(events)} events from {path}")
