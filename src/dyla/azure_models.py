"""Azure OpenAI implementations of the model provider contracts."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from types import TracebackType
from typing import Any, NoReturn, Self

import httpx
from pydantic import ValidationError

from .config import Settings
from .models import ModelCallError, ModelRequest, ModelResponse, ModelTelemetry


class EmbeddingCacheCompatibilityError(RuntimeError):
    """The on-disk embedding cache uses a schema this adapter cannot identify safely."""


class _AzureClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None,
        timeout: float,
        max_retries: int,
        sleeper: Callable[[float], None],
        backoff_base: float,
        model: str,
        input_cost_per_1k: float,
        output_cost_per_1k: float,
    ) -> None:
        self.endpoint = settings.azure_openai_endpoint.rstrip("/")
        self.api_key = settings.azure_openai_api_key
        self.api_version = settings.azure_openai_api_version
        self.client = httpx.Client(transport=transport, timeout=timeout)
        self.max_retries = max(0, max_retries)
        self.sleeper = sleeper
        self.backoff_base = max(0.0, backoff_base)
        self.model = model
        self.input_cost_per_1k = input_cost_per_1k
        self.output_cost_per_1k = output_cost_per_1k

    def post(self, deployment: str, payload: dict[str, Any]) -> tuple[dict[str, Any], int, int]:
        url = (
            f"{self.endpoint}/openai/deployments/{deployment}/chat/completions"
            if payload.get("messages") is not None
            else f"{self.endpoint}/openai/deployments/{deployment}/embeddings"
        )
        started = time.monotonic()
        for retry_count in range(self.max_retries + 1):
            try:
                response = self.client.post(
                    url,
                    params={"api-version": self.api_version},
                    headers={"api-key": self.api_key, "content-type": "application/json"},
                    json=payload,
                )
            except httpx.TimeoutException:
                if retry_count < self.max_retries:
                    self._wait(retry_count)
                    continue
                self._raise_failure(
                    deployment, retry_count, None, "request timed out", started
                )
            if response.status_code in {429, *range(500, 600)}:
                if retry_count < self.max_retries:
                    self._wait(retry_count)
                    continue
                self._raise_failure(
                    deployment, retry_count, response.status_code, "retry exhaustion", started
                )
            if response.is_error:
                detail = response.text.replace(self.api_key, "[REDACTED]")
                self._raise_failure(
                    deployment,
                    retry_count,
                    response.status_code,
                    f"HTTP {response.status_code}: {detail}",
                    started,
                )
            try:
                data = response.json()
            except json.JSONDecodeError:
                self._raise_failure(
                    deployment, retry_count, response.status_code,
                    "invalid JSON response", started
                )
            return data, retry_count, response.status_code
        raise AssertionError("unreachable")

    def _raise_failure(
        self,
        deployment: str,
        retry_count: int,
        status_code: int | None,
        error: str,
        started: float,
    ) -> NoReturn:
        telemetry = ModelTelemetry(
            deployment=deployment,
            model=self.model,
            input_cost_per_1k=self.input_cost_per_1k,
            output_cost_per_1k=self.output_cost_per_1k,
            retry_count=retry_count,
            status_code=status_code,
            error=error,
            latency_ms=int((time.monotonic() - started) * 1000),
        )
        redacted_error = error.replace(self.api_key, "[REDACTED]")
        telemetry = ModelTelemetry(
            input_tokens=telemetry.input_tokens,
            output_tokens=telemetry.output_tokens,
            latency_ms=telemetry.latency_ms,
            deployment=telemetry.deployment,
            model=telemetry.model,
            input_cost_per_1k=telemetry.input_cost_per_1k,
            output_cost_per_1k=telemetry.output_cost_per_1k,
            estimated_cost=telemetry.estimated_cost,
            retry_count=telemetry.retry_count,
            status_code=telemetry.status_code,
            error=redacted_error,
        )
        raise ModelCallError("Azure model call failed: " + redacted_error, telemetry)

    def _wait(self, retry_count: int) -> None:
        self.sleeper(self.backoff_base * (2**retry_count))

    def close(self) -> None:
        self.client.close()


class AzureChatModel:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        sleeper: Callable[[float], None] = time.sleep,
        backoff_base: float = 0.25,
        model_name: str | None = None,
        input_cost_per_1k: float = 0.0,
        output_cost_per_1k: float = 0.0,
    ) -> None:
        self.deployment = settings.azure_openai_chat_deployment
        self._client = _AzureClient(
            settings,
            transport=transport,
            timeout=timeout,
            max_retries=max_retries,
            sleeper=sleeper,
            backoff_base=backoff_base,
            model=model_name or self.deployment,
            input_cost_per_1k=input_cost_per_1k,
            output_cost_per_1k=output_cost_per_1k,
        )

    def complete(self, request: ModelRequest) -> ModelResponse:
        payload: dict[str, Any] = {
            "messages": request.messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        if request.response_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": request.response_schema.__name__,
                    "strict": True,
                    "schema": request.response_schema.model_json_schema(),
                },
            }
        started = time.monotonic()
        data, retry_count, status_code = self._client.post(self.deployment, payload)
        try:
            message = data["choices"][0]["message"]
            text = message.get("content") or ""
            if isinstance(text, list):
                text = "".join(part.get("text", "") for part in text)
            parsed = request.response_schema.model_validate_json(text) if request.response_schema else None
            usage = data.get("usage") or {}
            input_tokens = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)))
            output_tokens = int(usage.get("completion_tokens", usage.get("output_tokens", 0)))
        except ValidationError as exc:
            self._client._raise_failure(
                self.deployment, retry_count, status_code,
                f"response validation failed: {exc}", started
            )
        except (KeyError, IndexError, TypeError, AttributeError, ValueError) as exc:
            self._client._raise_failure(
                self.deployment, retry_count, status_code,
                f"malformed chat response: {exc}", started
            )
        estimated_cost = (
            input_tokens * self._client.input_cost_per_1k
            + output_tokens * self._client.output_cost_per_1k
        ) / 1000
        return ModelResponse(
            text=text,
            parsed=parsed,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=int((time.monotonic() - started) * 1000),
            deployment=self.deployment,
            model=self._client.model,
            input_cost_per_1k=self._client.input_cost_per_1k,
            output_cost_per_1k=self._client.output_cost_per_1k,
            estimated_cost=estimated_cost,
            retry_count=retry_count,
            status_code=status_code,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


class AzureEmbeddingModel:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
        cache_path: str | Path | None = None,
        batch_size: int = 16,
        timeout: float = 30.0,
        max_retries: int = 3,
        sleeper: Callable[[float], None] = time.sleep,
        backoff_base: float = 0.25,
        model_name: str | None = None,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        self.deployment = settings.azure_openai_embedding_deployment
        self.model = model_name or self.deployment
        self._client = _AzureClient(
            settings,
            transport=transport,
            timeout=timeout,
            max_retries=max_retries,
            sleeper=sleeper,
            backoff_base=backoff_base,
            model=self.model,
            input_cost_per_1k=0.0,
            output_cost_per_1k=0.0,
        )
        self.batch_size = batch_size
        self._cache: sqlite3.Connection | None = None
        self._cache_namespace = hashlib.sha256(
            json.dumps(
                {
                    "deployment": self.deployment,
                    "model": self.model,
                    "endpoint": self._client.endpoint,
                    "api_version": self._client.api_version,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        if cache_path is not None:
            self._cache = sqlite3.connect(str(cache_path))
            table = self._cache.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'embedding_cache'"
            ).fetchone()
            if table:
                columns = {
                    row[1]
                    for row in self._cache.execute("PRAGMA table_info(embedding_cache)")
                }
                if "content_hash" in columns and "cache_key" not in columns:
                    self._cache.close()
                    self._cache = None
                    self._client.close()
                    raise EmbeddingCacheCompatibilityError(
                        "embedding_cache uses legacy content_hash schema; "
                        "clear or migrate it before using namespaced embeddings"
                    )
                if not {"cache_key", "embedding_json"} <= columns:
                    self._cache.close()
                    self._cache = None
                    self._client.close()
                    raise EmbeddingCacheCompatibilityError(
                        "embedding_cache schema is incompatible with namespaced embeddings"
                    )
            else:
                self._cache.execute(
                    "CREATE TABLE embedding_cache "
                    "(cache_key TEXT PRIMARY KEY, embedding_json TEXT NOT NULL)"
                )
            self._cache.commit()

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        result: list[list[float] | None] = [None] * len(texts)
        missing: list[tuple[int, str, str]] = []
        for index, text in enumerate(texts):
            key = self._cache_key(text)
            cached = self._read_cache(key)
            if cached is None:
                missing.append((index, text, key))
            else:
                result[index] = cached
        for start in range(0, len(missing), self.batch_size):
            batch = missing[start : start + self.batch_size]
            started = time.monotonic()
            data, retry_count, status_code = self._client.post(
                self.deployment, {"input": [text for _, text, _ in batch]}
            )
            try:
                vectors = sorted(data.get("data", []), key=lambda item: item["index"])
                if len(vectors) != len(batch):
                    raise ValueError("response vector count did not match requested batch")
                for (index, _, key), item in zip(batch, vectors):
                    vector = [float(value) for value in item["embedding"]]
                    result[index] = vector
                    self._write_cache(key, vector)
            except (KeyError, IndexError, TypeError, AttributeError, ValueError) as exc:
                self._client._raise_failure(
                    self.deployment, retry_count, status_code,
                    f"malformed embedding response: {exc}", started
                )
        return [vector for vector in result if vector is not None]

    def _cache_key(self, text: str) -> str:
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return f"{self._cache_namespace}:{content_hash}"

    def _read_cache(self, key: str) -> list[float] | None:
        if self._cache is None:
            return None
        row = self._cache.execute(
            "SELECT embedding_json FROM embedding_cache WHERE cache_key = ?", (key,)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def _write_cache(self, key: str, vector: list[float]) -> None:
        if self._cache is None:
            return
        self._cache.execute(
            "INSERT OR REPLACE INTO embedding_cache VALUES (?, ?)", (key, json.dumps(vector))
        )
        self._cache.commit()

    def close(self) -> None:
        if self._cache is not None:
            self._cache.close()
            self._cache = None
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
