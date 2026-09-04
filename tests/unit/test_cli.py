import json
from types import SimpleNamespace

import pytest
from typer import BadParameter
from typer.testing import CliRunner

from dyla.cli import _build_orchestrator, app
from dyla.domain import AnalystAnswer, Metrics
from dyla.orchestrator import RunResult
from dyla.reliability import QualityResult


def test_console_entry_point_is_importable():
    assert callable(app)


def test_ask_json_includes_computed_metrics(monkeypatch, tmp_path):
    answer = AnalystAnswer(answer="answer", claims=[], limitations=[])
    metrics = Metrics(input_tokens=3, output_tokens=4, estimated_cost=0.5,
                      duration_ms=8, searches=2, fetches=1, memory_hits=6, parallel_calls=1)

    class Orchestrator:
        async def ask(self, question):
            return RunResult("run-1", answer, [], QualityResult("unaudited", []), metrics,
                             tmp_path / "run-1.jsonl")

    monkeypatch.setattr("dyla.cli.load_settings", lambda: object())
    monkeypatch.setattr("dyla.cli._build_orchestrator", lambda settings: Orchestrator())

    result = CliRunner().invoke(app, ["ask", "question", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.stdout)["metrics"] == metrics.model_dump()


def test_analyst_command_runs_only_the_analyst_stage(monkeypatch):
    calls = []

    class Analyst:
        async def run(self, question, run_id):
            calls.append(("analyst", question, run_id))
            return AnalystAnswer(answer="analyst answer", claims=[], limitations=[])

    monkeypatch.setattr("dyla.cli.load_settings", lambda: object())
    monkeypatch.setattr("dyla.cli._build_analyst", lambda settings: Analyst())

    result = CliRunner().invoke(app, ["analyst", "question"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "analyst answer"
    assert [call[0] for call in calls] == ["analyst"]


def test_build_orchestrator_wires_configured_auditor_timeout_and_retries(monkeypatch):
    class Analyst:
        fetcher = object()
        memory = object()

    monkeypatch.setattr("dyla.cli._build_analyst", lambda settings: Analyst())
    monkeypatch.setattr("dyla.cli.build_auditor_provider", lambda settings: object())
    settings = SimpleNamespace(auditor_timeout_seconds=123.5, auditor_retries=4)

    orchestrator = _build_orchestrator(settings)

    assert orchestrator.auditor.timeout_seconds == 123.5
    assert orchestrator.auditor.retries == 4


def test_audit_and_replay_accept_trace_artifacts_and_run_ids(tmp_path, monkeypatch):
    trace = tmp_path / "custom-trace.jsonl"
    trace.write_text(json.dumps({"event": "claim_audited", "payload": {"claim_id": "c1"}}) + "\n")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "run-1.jsonl").write_text(trace.read_text())

    runner = CliRunner()
    audit = runner.invoke(app, ["audit", str(trace), "--json"])
    replay = runner.invoke(app, ["replay", str(trace), "--json"])
    audit_by_id = runner.invoke(app, ["audit", "run-1"])

    assert audit.exit_code == 0
    assert json.loads(audit.stdout)[0]["event"] == "claim_audited"
    assert replay.exit_code == 0
    assert len(json.loads(replay.stdout)) == 1
    assert audit_by_id.exit_code == 0
    assert "Verdicts: 1" in audit_by_id.stdout


def test_read_trace_rejects_non_object_json_values(tmp_path):
    from dyla.cli import _read_trace

    artifact = tmp_path / "not-an-event.jsonl"
    artifact.write_text("[1, 2, 3]\n")

    with pytest.raises(BadParameter, match="JSON object"):
        _read_trace(str(artifact))


def test_evaluate_writes_json_and_markdown_reports(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    class Orchestrator:
        async def ask(self, question):
            return type("Result", (), {
                "quality": type("Quality", (), {"status": "complete"})(),
                "run_id": question,
                "metrics": type("Metrics", (), {"model_dump": lambda self, **kwargs: {}})(),
            })()

    monkeypatch.setattr("dyla.config.load_settings", lambda: object())
    monkeypatch.setattr("dyla.cli._build_orchestrator", lambda settings: Orchestrator())

    result = CliRunner().invoke(app, ["evaluate", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.stdout)["total"] == 8
    assert json.loads((tmp_path / "reports" / "evaluation.json").read_text())["passed"] == 8
    assert "# Evaluation" in (tmp_path / "reports" / "evaluation.md").read_text()


def test_evaluate_accepts_questions_file_override(tmp_path, monkeypatch):
    questions_file = tmp_path / "questions.txt"
    questions_file.write_text(
        "\nWhat is the current GST rate on restaurant services in India?\n\nWho leads Zerodha?\n"
    )
    asked = []

    class Orchestrator:
        async def ask(self, question):
            asked.append(question)
            return type("Result", (), {
                "quality": type("Quality", (), {"status": "complete"})(),
                "run_id": question,
                "metrics": type("Metrics", (), {"model_dump": lambda self, **kwargs: {}})(),
            })()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("dyla.config.load_settings", lambda: object())
    monkeypatch.setattr("dyla.cli._build_orchestrator", lambda settings: Orchestrator())

    result = CliRunner().invoke(app, ["evaluate", "--json", "--questions-file", str(questions_file)])

    assert result.exit_code == 0
    assert json.loads(result.stdout)["total"] == 2
    assert asked == [
        "What is the current GST rate on restaurant services in India?",
        "Who leads Zerodha?",
    ]
    assert json.loads((tmp_path / "reports" / "evaluation.json").read_text())["total"] == 2


def test_evaluate_rejects_empty_questions_file(tmp_path):
    questions_file = tmp_path / "empty.txt"
    questions_file.write_text("\n   \n")

    result = CliRunner().invoke(app, ["evaluate", "--json", "--questions-file", str(questions_file)])

    assert result.exit_code != 0
    assert "no questions" in result.output
