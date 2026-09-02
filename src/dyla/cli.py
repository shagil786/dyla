"""Typer command line interface for Dyla research runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from .analyst import AnalystAgent
from .auditor import AuditorAgent
from .azure_models import AzureChatModel, AzureEmbeddingModel
from .config import Settings, load_settings
from .entities import EntityResolver
from .memory import MemoryStore
from .orchestrator import RunOrchestrator, RunResult
from .provider_factory import build_search_provider
from .search import SearchIndex
from .tracing import TraceWriter

app = typer.Typer(help="Research questions with cited, independently audited evidence.")
memory_app = typer.Typer(help="Inspect durable research memory.")
app.add_typer(memory_app, name="memory")


def _build_memory(settings: Settings) -> MemoryStore:
    del settings
    store = MemoryStore()
    store.initialize()
    return store


def _build_orchestrator(settings: Settings) -> RunOrchestrator:
    memory = _build_memory(settings)
    provider = build_search_provider(settings)
    model = AzureChatModel(settings)
    embedder = AzureEmbeddingModel(settings, cache_path="dyla.db")
    index = SearchIndex(settings, embedder=embedder)
    analyst = AnalystAgent(
        model=model, resolver=EntityResolver(memory), memory=memory,
        searcher=provider, fetcher=provider, index=index, embedder=embedder,
        trace_writer=TraceWriter(),
    )
    auditor = AuditorAgent(fetcher=provider, trace_writer=TraceWriter())
    return RunOrchestrator(analyst=analyst, auditor=auditor, memory=memory, trace_writer=TraceWriter())


def _print_result(result: RunResult, json_output: bool) -> None:
    payload = {
        "run_id": result.run_id,
        "answer": result.answer.model_dump(mode="json"),
        "verdicts": [item.model_dump(mode="json") for item in result.verdicts],
        "quality": {"status": result.quality.status, "issues": result.quality.issues},
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
    result = __import__("asyncio").run(_build_orchestrator(load_settings()).ask(question))
    data: Any = result.answer.model_dump(mode="json") if json_output else result.answer.answer
    typer.echo(json.dumps(data, indent=2) if json_output else data)


@app.command()
def audit(run_id: str, json_output: bool = typer.Option(False, "--json")) -> None:
    """Show audit verdicts saved in a run trace."""
    path = Path("logs") / f"{run_id}.jsonl"
    if not path.is_file():
        raise typer.BadParameter(f"run trace not found: {path}")
    events = [json.loads(line) for line in path.read_text().splitlines()]
    verdicts = [event for event in events if event.get("event") == "claim_audited"]
    typer.echo(json.dumps(verdicts, indent=2) if json_output else f"Verdicts: {len(verdicts)}")


@app.command()
def evaluate(json_output: bool = typer.Option(False, "--json")) -> None:
    """Report that evaluation is available through the configured question set."""
    payload = {"status": "not_configured", "message": "No evaluation question set was supplied."}
    typer.echo(json.dumps(payload) if json_output else payload["message"])


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
def replay(run_id: str, json_output: bool = typer.Option(False, "--json")) -> None:
    """Replay a saved trace without making model or web calls."""
    path = Path("logs") / f"{run_id}.jsonl"
    if not path.is_file():
        raise typer.BadParameter(f"run trace not found: {path}")
    events = [json.loads(line) for line in path.read_text().splitlines()]
    typer.echo(json.dumps(events, indent=2) if json_output else f"Replayed {len(events)} events from {path}")
