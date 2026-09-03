"""OpenAI-compatible HTTP model and embedding adapters."""
from __future__ import annotations
import hashlib
import json
import sqlite3
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
import httpx
from pydantic import ValidationError
from .models import ModelCallError, ModelRequest, ModelResponse, ModelTelemetry


def normalize_base_url(value: str) -> str:
    base = value.strip().rstrip("/")
    for suffix in ("/chat/completions", "/embeddings"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
    if not base.endswith("/v1"):
        base += "/v1"
    return base


class _CompatibleClient:
    def __init__(self, base_url: str, api_key: str, *, transport: httpx.BaseTransport | None,
                 timeout: float, max_retries: int, sleeper: Callable[[float], None]) -> None:
        if not base_url or not api_key:
            raise ValueError("compatible provider base URL and API key are required")
        self.base_url = normalize_base_url(base_url)
        self.api_key = api_key
        self.client = httpx.Client(transport=transport, timeout=timeout)
        self.max_retries = max(0, max_retries)
        self.sleeper = sleeper

    def post(self, path: str, payload: dict[str, Any], *, operation: str, model: str):
        started = time.monotonic()
        for retry in range(self.max_retries + 1):
            try:
                response = self.client.post(f"{self.base_url}/{path}", headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}, json=payload)
            except httpx.TimeoutException:
                if retry < self.max_retries:
                    self.sleeper(0.25 * (2 ** retry)); continue
                self._fail(operation, model, retry, None, "request timed out", started)
            if response.status_code == 429 or response.status_code >= 500:
                if retry < self.max_retries:
                    self.sleeper(0.25 * (2 ** retry)); continue
                self._fail(operation, model, retry, response.status_code, "retry exhaustion", started)
            if response.is_error:
                self._fail(operation, model, retry, response.status_code, f"HTTP {response.status_code}: {response.text.replace(self.api_key, '[REDACTED]')}", started)
            try:
                return response.json(), retry, response.status_code
            except json.JSONDecodeError:
                self._fail(operation, model, retry, response.status_code, "invalid JSON response", started)
        raise AssertionError("unreachable")

    def _fail(self, operation, model, retry, status, error, started):
        error = error.replace(self.api_key, "[REDACTED]")
        telemetry = ModelTelemetry(model=model, deployment=model, retry_count=retry, status_code=status, error=error, latency_ms=int((time.monotonic() - started) * 1000))
        raise ModelCallError(f"Compatible {operation} call failed: {error}", telemetry)

    def close(self):
        self.client.close()


class CompatibleModelProvider:
    def __init__(self, base_url, api_key, model, *, transport=None, timeout=30.0, max_retries=3, sleeper=time.sleep):
        self.model = model
        self._client = _CompatibleClient(base_url, api_key, transport=transport, timeout=timeout, max_retries=max_retries, sleeper=sleeper)

    def complete(self, request: ModelRequest) -> ModelResponse:
        payload = {"messages": request.messages, "model": self.model, "max_tokens": request.max_tokens, "temperature": request.temperature}
        if request.response_schema is not None:
            payload["response_format"] = {"type": "json_schema", "json_schema": {"name": request.response_schema.__name__, "strict": True, "schema": request.response_schema.model_json_schema()}}
        started = time.monotonic()
        data, retry, status = self._client.post("chat/completions", payload, operation="model", model=self.model)
        try:
            text = data["choices"][0]["message"].get("content") or ""
            if isinstance(text, list):
                text = "".join(part.get("text", "") for part in text)
            parsed = request.response_schema.model_validate_json(text) if request.response_schema else None
            usage = data.get("usage") or {}
            input_tokens = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)))
            output_tokens = int(usage.get("completion_tokens", usage.get("output_tokens", 0)))
        except (ValidationError, KeyError, IndexError, TypeError, AttributeError, ValueError) as exc:
            self._client._fail("model", self.model, retry, status, f"malformed chat response: {exc}", started)
        return ModelResponse(text=text, parsed=parsed, input_tokens=input_tokens, output_tokens=output_tokens, latency_ms=int((time.monotonic() - started) * 1000), deployment=self.model, model=self.model, retry_count=retry, status_code=status)

    def close(self):
        self._client.close()


class CompatibleEmbeddingProvider:
    def __init__(
        self,
        base_url,
        api_key,
        model,
        *,
        transport=None,
        cache_path: str | Path | None = None,
        batch_size: int = 256,
        timeout=30.0,
        max_retries=3,
        sleeper=time.sleep,
    ):
        if not 1 <= batch_size <= 256:
            raise ValueError("batch_size must be between 1 and 256")
        self.model = model
        self._client = _CompatibleClient(base_url, api_key, transport=transport, timeout=timeout, max_retries=max_retries, sleeper=sleeper)
        self.batch_size = batch_size
        self._cache: sqlite3.Connection | None = None
        self._cache_lock = threading.RLock()
        self._cache_namespace = hashlib.sha256(
            json.dumps({"endpoint": self._client.base_url, "model": self.model}, sort_keys=True).encode()
        ).hexdigest()
        if cache_path is not None:
            with self._cache_lock:
                self._cache = sqlite3.connect(str(cache_path), check_same_thread=False)
                table = self._cache.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'embedding_cache'"
                ).fetchone()
                if table:
                    columns = {row[1] for row in self._cache.execute("PRAGMA table_info(embedding_cache)")}
                    if not {"cache_key", "embedding_json"} <= columns:
                        self._cache.close()
                        self._cache = None
                        self._client.close()
                        raise RuntimeError("embedding_cache schema is incompatible with namespaced embeddings")
                else:
                    self._cache.execute(
                        "CREATE TABLE embedding_cache (cache_key TEXT PRIMARY KEY, embedding_json TEXT NOT NULL)"
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
            data, _, _ = self._client.post(
                "embeddings",
                {"input": [text for _, text, _ in batch], "model": self.model},
                operation="embedding",
                model=self.model,
            )
            try:
                values = sorted(data["data"], key=lambda item: item["index"])
                if len(values) != len(batch):
                    raise ValueError("response vector count did not match requested input count")
                for (index, _, key), item in zip(batch, values):
                    vector = [float(value) for value in item["embedding"]]
                    result[index] = vector
                    self._write_cache(key, vector)
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                self._client._fail("embedding", self.model, 0, None, f"malformed embedding response: {exc}", time.monotonic())
        return [vector for vector in result if vector is not None]

    def _cache_key(self, text: str) -> str:
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return f"{self._cache_namespace}:{content_hash}"

    def _read_cache(self, key: str) -> list[float] | None:
        with self._cache_lock:
            if self._cache is None:
                return None
            row = self._cache.execute(
                "SELECT embedding_json FROM embedding_cache WHERE cache_key = ?", (key,)
            ).fetchone()
            return json.loads(row[0]) if row else None

    def _write_cache(self, key: str, vector: list[float]) -> None:
        with self._cache_lock:
            if self._cache is None:
                return
            self._cache.execute(
                "INSERT OR REPLACE INTO embedding_cache VALUES (?, ?)", (key, json.dumps(vector))
            )
            self._cache.commit()

    def close(self):
        with self._cache_lock:
            if self._cache is not None:
                self._cache.close()
                self._cache = None
        self._client.close()


class LocalModelProvider:
    def complete(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(text="", parsed=None, input_tokens=0, output_tokens=0, latency_ms=0, model="local", deployment="local")


class LocalEmbeddingProvider:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(sum(text.encode("utf-8")) % 997), float(len(text))] for text in texts]
