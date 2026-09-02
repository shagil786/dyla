"""Deterministic, redacted JSONL run tracing."""

import json
import re
from pathlib import Path
from typing import Any

from dyla.domain import RunEvent

_SENSITIVE_KEY = re.compile(r"(?:api_key|authorization|token|secret)", re.IGNORECASE)
_REDACTED = "[REDACTED]"


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _REDACTED if _SENSITIVE_KEY.search(str(key)) else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


class TraceWriter:
    """Append stable, one-event-per-line traces beneath a log directory."""

    def __init__(self, root: str | Path = ".") -> None:
        self.root = Path(root)

    def append(self, event: RunEvent) -> None:
        log_dir = self.root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        record = _redact(event.model_dump(mode="json"))
        line = json.dumps(record, sort_keys=True, separators=(",", ":"))
        with (log_dir / f"{event.run_id}.jsonl").open("a", encoding="utf-8") as trace_file:
            trace_file.write(line + "\n")
