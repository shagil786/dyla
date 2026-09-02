"""Azure OpenAI implementations of the model provider contracts."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from .config import Settings
from .models import ModelRequest, ModelResponse


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
    ) -> None:
        self.endpoint = settings.azure_openai_endpoint.rstrip("/")
        self.api_key = settings.azure_openai_api_key
        self.api_version = settings.azure_openai_api_version
        self.client = httpx.Client(transport=transport, timeout=timeout)
        self.max_retries = max(0, max_retries)
        self.sleeper = sleeper
        self.backoff_base = max(0.0, backoff_base)

    def post(self, deployment: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = (
            f"{self.endpoint}/openai/deployments/{deployment}/chat/completions"
            if payload.get("messages") is not None
            else f"{self.endpoint}/openai/deployments/{deployment}/embeddings"
        )
        params = {"api-version": self.api_version}
        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.post(
                    url,
                    params=params,
                    headers={"api-key": self.api_key, "content-type": "application/json"},
                    json=payload,
                )
            except httpx.TimeoutException:
                if attempt >= self.max_retries:
                    raise RuntimeError("Azure request timed out") from None
                self._wait(attempt)
                continue
            if response.status_code not in {429, *range(500, 600)}:
                if response.is_error:
                    detail = response.text.replace(self.api_key, "[REDACTED]")
                    raise RuntimeError(
                        f"Azure request failed with HTTP {response.status_code}: {detail}"
                    )
                return response.json()
            if attempt >= self.max_retries:
                raise RuntimeError(
                    f"Azure request failed after {self.max_retries + 1} attempts "
                    f"with HTTP {response.status_code}"
                )
            self._wait(attempt)
        raise RuntimeError("Azure request failed")

    def _wait(self, attempt: int) -> None:
        self.sleeper(self.backoff_base * (2**attempt))


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
    ) -> None:
        self._client = _AzureClient(
            settings,
            transport=transport,
            timeout=timeout,
            max_retries=max_retries,
            sleeper=sleeper,
            backoff_base=backoff_base,
        )
        self.deployment = settings.azure_openai_chat_deployment

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
        data = self._client.post(self.deployment, payload)
        message = data["choices"][0]["message"]
        text = message.get("content") or ""
        if isinstance(text, list):
            text = "".join(part.get("text", "") for part in text)
        parsed = request.response_schema.model_validate_json(text) if request.response_schema else None
        usage = data.get("usage") or {}
        return ModelResponse(
            text=text,
            parsed=parsed,
            input_tokens=int(usage.get("prompt_tokens", usage.get("input_tokens", 0))),
            output_tokens=int(usage.get("completion_tokens", usage.get("output_tokens", 0))),
            latency_ms=int((time.monotonic() - started) * 1000),
        )


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
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        self._client = _AzureClient(
            settings,
            transport=transport,
            timeout=timeout,
            max_retries=max_retries,
            sleeper=sleeper,
            backoff_base=backoff_base,
        )
        self.deployment = settings.azure_openai_embedding_deployment
        self.batch_size = batch_size
        self._cache = None
        if cache_path is not None:
            import sqlite3

            self._cache = sqlite3.connect(str(cache_path))
            self._cache.execute(
                "CREATE TABLE IF NOT EXISTS embedding_cache "
                "(content_hash TEXT PRIMARY KEY, embedding_json TEXT NOT NULL)"
            )
            self._cache.commit()

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        result: list[list[float] | None] = [None] * len(texts)
        missing: list[tuple[int, str, str]] = []
        for index, text in enumerate(texts):
            key = hashlib.sha256(text.encode("utf-8")).hexdigest()
            cached = self._read_cache(key)
            if cached is None:
                missing.append((index, text, key))
            else:
                result[index] = cached
        for start in range(0, len(missing), self.batch_size):
            batch = missing[start : start + self.batch_size]
            data = self._client.post(self.deployment, {"input": [text for _, text, _ in batch]})
            vectors = sorted(data.get("data", []), key=lambda item: item["index"])
            if len(vectors) != len(batch):
                raise RuntimeError("Azure embedding response did not match the requested batch")
            for (index, _, key), item in zip(batch, vectors):
                vector = [float(value) for value in item["embedding"]]
                result[index] = vector
                self._write_cache(key, vector)
        return [vector for vector in result if vector is not None]

    def _read_cache(self, key: str) -> list[float] | None:
        if self._cache is None:
            return None
        row = self._cache.execute(
            "SELECT embedding_json FROM embedding_cache WHERE content_hash = ?", (key,)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def _write_cache(self, key: str, vector: list[float]) -> None:
        if self._cache is None:
            return
        self._cache.execute(
            "INSERT OR REPLACE INTO embedding_cache VALUES (?, ?)", (key, json.dumps(vector))
        )
        self._cache.commit()
