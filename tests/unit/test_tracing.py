import json
from datetime import UTC, datetime

import pytest

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


def test_trace_writer_redacts_secret_text_in_error_and_nested_tuples(tmp_path):
    event = RunEvent(
        run_id="run-3",
        timestamp=datetime(2026, 9, 2, tzinfo=UTC),
        component="test",
        event="failed",
        payload={"items": ("authorization=tuple-secret", {"safe": "ok"})},
        duration_ms=None,
        error="request failed: authorization=real-secret",
    )

    TraceWriter(tmp_path).append(event)

    contents = (tmp_path / "logs" / "run-3.jsonl").read_text()
    assert "real-secret" not in contents
    assert "tuple-secret" not in contents
    assert "[REDACTED]" in contents


def test_trace_writer_rejects_run_ids_that_escape_logs_directory(tmp_path):
    event = RunEvent(
        run_id="../outside",
        timestamp=datetime(2026, 9, 2, tzinfo=UTC),
        component="test",
        event="started",
        payload={},
        duration_ms=None,
        error=None,
    )

    with pytest.raises(ValueError, match="safe filename"):
        TraceWriter(tmp_path).append(event)

    absolute_event = event.model_copy(update={"run_id": "/tmp/outside"})
    with pytest.raises(ValueError, match="safe filename"):
        TraceWriter(tmp_path).append(absolute_event)
