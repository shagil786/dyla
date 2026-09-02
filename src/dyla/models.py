"""Provider contracts for chat completion and text embedding services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel


@dataclass(frozen=True)
class ModelRequest:
    messages: list[dict[str, str]]
    response_schema: type[BaseModel] | None
    max_tokens: int
    temperature: float


@dataclass(frozen=True)
class ModelTelemetry:
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    deployment: str = ""
    model: str = ""
    input_cost_per_1k: float = 0.0
    output_cost_per_1k: float = 0.0
    estimated_cost: float = 0.0
    retry_count: int = 0
    status_code: int | None = None
    error: str | None = None


@dataclass(frozen=True)
class ModelResponse:
    text: str
    parsed: BaseModel | None
    input_tokens: int
    output_tokens: int
    latency_ms: int
    deployment: str = ""
    model: str = ""
    input_cost_per_1k: float = 0.0
    output_cost_per_1k: float = 0.0
    estimated_cost: float = 0.0
    retry_count: int = 0
    status_code: int | None = None
    error: str | None = None


class ModelCallError(RuntimeError):
    """A failed model call carrying the telemetry collected before failure."""

    def __init__(self, message: str, telemetry: ModelTelemetry) -> None:
        super().__init__(message)
        self.telemetry = telemetry


class ModelProvider(Protocol):
    def complete(self, request: ModelRequest) -> ModelResponse:
        """Complete a chat request."""
        ...


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector for each input text, in input order."""
        ...
