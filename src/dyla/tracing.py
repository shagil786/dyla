"""Deterministic, redacted JSONL run tracing."""

import json
import re
from pathlib import Path
from typing import Any

from dyla.domain import RunEvent

_SENSITIVE_KEY = re.compile(r"(?:api_key|authorization|token|secret)", re.IGNORECASE)
_SENSITIVE_TEXT = re.compile(
    r"(\b(?:api_key|authorization|token|secret)\b\s*[=:]\s*)([^\s,;\"']+)",
    re.IGNORECASE,
)
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_REDACTED = "[REDACTED]"


def _sanitize_string(value: str) -> str:
    return _SENSITIVE_TEXT.sub(r"\1" + _REDACTED, value)


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        return _sanitize_string(value)
    if isinstance(value, dict):
        return {
            _sanitize_string(str(key)):
            _REDACTED if _SENSITIVE_KEY.search(str(key)) else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item) for item in value)
    return value


class TraceWriter:
    """Append stable, one-event-per-line traces beneath a log directory."""

    def __init__(self, root: str | Path = ".") -> None:
        self.root = Path(root)

    def append(self, event: RunEvent) -> None:
        if not _SAFE_RUN_ID.fullmatch(event.run_id):
            raise ValueError("run_id must be a safe filename component")

        log_dir = self.root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        record = _redact(event.model_dump(mode="json"))
        line = json.dumps(record, sort_keys=True, separators=(",", ":"))
        with (log_dir / f"{event.run_id}.jsonl").open("a", encoding="utf-8") as trace_file:
            trace_file.write(line + "\n")
