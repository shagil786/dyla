from typer.testing import CliRunner

from dyla.cli import app


def test_cli_exposes_full_command_structure():
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    for command in ("ask", "analyst", "audit", "evaluate", "memory", "replay"):
        assert command in result.stdout


def test_memory_list_command_outputs_records(monkeypatch):
    class Memory:
        def initialize(self):
            pass

        def search_memory(self, query, limit):
            return []

    monkeypatch.setattr("dyla.cli.load_settings", lambda: object())
    monkeypatch.setattr("dyla.cli._build_memory", lambda settings: Memory())
    runner = CliRunner()
    result = runner.invoke(app, ["memory", "list", "--query", "fact"])

    assert result.exit_code == 0
    assert "No memory records" in result.stdout
