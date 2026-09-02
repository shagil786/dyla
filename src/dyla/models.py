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
class ModelResponse:
    text: str
    parsed: BaseModel | None
    input_tokens: int
    output_tokens: int
    latency_ms: int


class ModelProvider(Protocol):
    def complete(self, request: ModelRequest) -> ModelResponse:
        """Complete a chat request."""
        ...


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector for each input text, in input order."""
        ...
