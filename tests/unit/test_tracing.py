import json
from datetime import UTC, datetime

from dyla.domain import RunEvent
from dyla.tracing import TraceWriter


def test_trace_writer_appends_deterministic_redacted_jsonl(tmp_path):
    event = RunEvent(
        run_id="run-1",
        timestamp=datetime(2026, 9, 2, 12, 0, tzinfo=UTC),
        component="research",
        event="completed",
        payload={
            "zeta": "last",
            "api_key": "top-secret",
            "nested": {"Authorization": "bearer secret", "safe": 3},
            "items": [{"token": "hidden", "value": "visible"}],
        },
        duration_ms=42,
        error=None,
    )

    TraceWriter(tmp_path).append(event)

    trace_path = tmp_path / "logs" / "run-1.jsonl"
    assert trace_path.read_text() == (
        '{"component":"research","duration_ms":42,"error":null,'
        '"event":"completed","payload":{"api_key":"[REDACTED]",'
        '"items":[{"token":"[REDACTED]","value":"visible"}],'
        '"nested":{"Authorization":"[REDACTED]","safe":3},'
        '"zeta":"last"},"run_id":"run-1",'
        '"timestamp":"2026-09-02T12:00:00Z"}\n'
    )

    TraceWriter(tmp_path).append(event)
    lines = trace_path.read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0]) == json.loads(lines[1])


def test_trace_writer_creates_log_directory_and_redacts_matching_key_names(tmp_path):
    event = RunEvent(
        run_id="run-2",
        timestamp=datetime(2026, 9, 2, tzinfo=UTC),
        component="test",
        event="failed",
        payload={"client_secret_value": "hidden", "context": {"my_token_count": 2}},
        duration_ms=None,
        error="failure",
    )

    TraceWriter(tmp_path).append(event)

    trace_path = tmp_path / "logs" / "run-2.jsonl"
    assert trace_path.exists()
    assert "hidden" not in trace_path.read_text()
