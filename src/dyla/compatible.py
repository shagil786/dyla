"""OpenAI-compatible HTTP model and embedding adapters."""
from __future__ import annotations
import hashlib
import json
import re
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


def _parse_structured(text: str, schema: Any) -> Any:
    try:
        return schema.model_validate_json(text)
    except ValidationError as exc:
        failure = exc
    candidates = _json_candidates(text)
    for candidate in candidates:
        try:
            return schema.model_validate(candidate)
        except ValidationError as exc:
            failure = exc
    # Salvage is a last resort, attempted only after every candidate has failed
    # to validate outright. Running it inline with the loop above regressed the
    # truncation repair: for a response cut off mid-claim, the *first* candidate
    # is the raw truncated parse and a later one is the cleanly drop-repaired
    # version. Salvaging the first would keep a half-written claim in preference
    # to the repair that correctly discards it.
    for candidate in candidates:
        salvaged = _salvage_claims(candidate, schema)
        if salvaged is not None:
            return salvaged
    raise failure


# Keys a claim must carry to be worth keeping. ``citations`` is deliberately
# absent: a claim missing it is kept *without* citations so the analyst's
# existing no_citations gate rejects it and traces the rejection.
_CLAIM_REQUIRED = ("id", "text")


def _salvage_claims(candidate: Any, schema: Any) -> Any:
    """Recover the well-formed claims from an otherwise-valid answer.

    Observed live: a model returns a good answer where *one* claim omits
    ``citations``. Pydantic rejects the whole object, the adapter raises, and
    the question fails outright -- so one malformed claim out of four discards
    the three that were perfectly cited. That is a parser failure being
    reported as a research failure.

    The repair is deliberately narrow, because the tempting version is
    dangerous. **A missing ``citations`` field is never defaulted to anything
    that looks cited.** The claim is passed through with an empty citation
    list, which routes it straight into the analyst's existing ``no_citations``
    rejection and a traced course correction. Inventing ``citations: []`` as a
    schema default would have the same parse result and a much worse meaning:
    an uncited assertion would become a *valid* claim object, and the one thing
    this system must never do is manufacture provenance.

    Claims missing ``id`` or ``text`` are dropped entirely -- there is nothing
    to audit and no way to name what was lost. If nothing survives, the caller
    still raises the original error rather than returning an empty answer that
    would read as "the model found nothing".
    """
    if not isinstance(candidate, dict) or not isinstance(candidate.get("claims"), list):
        return None
    kept: list[dict] = []
    for claim in candidate["claims"]:
        if not isinstance(claim, dict):
            continue
        if any(not claim.get(field) for field in _CLAIM_REQUIRED):
            continue
        repaired = dict(claim)
        citations = repaired.get("citations")
        if not isinstance(citations, list):
            repaired["citations"] = []
        else:
            repaired["citations"] = [c for c in citations if isinstance(c, dict) and c.get("url")]
        kept.append(repaired)
    if not kept:
        return None
    try:
        return schema.model_validate({**candidate, "claims": kept})
    except ValidationError:
        return None


def _json_candidates(text: str) -> list[Any]:
    candidates: list[Any] = []
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    if cleaned and cleaned != text.strip():
        _try_parse_json(cleaned, candidates)
    for block in re.findall(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL):
        _try_parse_json(block.strip(), candidates)
    if (repaired := _repair_truncated_json(cleaned or text)) is not None:
        _try_parse_json(repaired, candidates)
    for variant in _truncated_drop_variants(cleaned or text):
        _try_parse_json(variant, candidates)
    if (balanced := _balanced_object(text)) is not None:
        _try_parse_json(balanced, candidates)
    return candidates


def _repair_truncated_json(text: str) -> str | None:
    start = text.find("{")
    if start == -1:
        return None
    snippet = text[start:].rstrip()
    closers, in_string = _unclosed_closers(snippet)
    repaired = snippet + ('"' if in_string else "")
    if repaired.endswith(","):
        repaired = repaired[:-1]
    elif repaired.endswith(":"):
        repaired += " null"
    return repaired + "".join(reversed(closers))


def _truncated_drop_variants(text: str) -> list[str]:
    start = text.find("{")
    if start == -1:
        return []
    snippet = text[start:].rstrip()
    variants: list[str] = []
    for dropped in range(1, 5):
        cut = -1
        seen = 0
        for index in range(len(snippet) - 1, -1, -1):
            if snippet[index] in ("}", "]"):
                seen += 1
                if seen == dropped:
                    cut = index
                    break
        if cut == -1:
            break
        variant = snippet[:cut].rstrip()
        if variant.endswith(","):
            variant = variant[:-1]
        closers, in_string = _unclosed_closers(variant)
        variants.append(variant + ('"' if in_string else "") + "".join(reversed(closers)))
    return variants


def _unclosed_closers(snippet: str) -> tuple[list[str], bool]:
    closers: list[str] = []
    in_string = False
    escaped = False
    for char in snippet:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            closers.append("}")
        elif char == "[":
            closers.append("]")
        elif char in ("}", "]") and closers and closers[-1] == char:
            closers.pop()
    return closers, in_string


def _try_parse_json(raw: str, candidates: list[Any]) -> None:
    try:
        candidates.append(json.loads(raw))
    except json.JSONDecodeError:
        pass


def _balanced_object(text: str) -> str | None:
    start = text.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[start : index + 1]
        start = text.find("{", start + 1)
    return None


class CompatibleModelProvider:
    def __init__(self, base_url, api_key, model, *, transport=None, timeout=30.0, max_retries=3, sleeper=time.sleep, extra_payload: dict[str, Any] | None = None):
        self.model = model
        self.extra_payload = extra_payload or None
        self._client = _CompatibleClient(base_url, api_key, transport=transport, timeout=timeout, max_retries=max_retries, sleeper=sleeper)

    def complete(self, request: ModelRequest) -> ModelResponse:
        payload = {"messages": request.messages, "model": self.model, "max_tokens": request.max_tokens, "temperature": request.temperature}
        if request.response_schema is not None:
            payload["response_format"] = {"type": "json_schema", "json_schema": {"name": request.response_schema.__name__, "strict": True, "schema": request.response_schema.model_json_schema()}}
        if self.extra_payload:
            payload.update(self.extra_payload)
        started = time.monotonic()
        data, retry, status = self._client.post("chat/completions", payload, operation="model", model=self.model)
        try:
            text = data["choices"][0]["message"].get("content") or ""
            if isinstance(text, list):
                text = "".join(part.get("text", "") for part in text)
            parsed = _parse_structured(text, request.response_schema) if request.response_schema else None
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
            self._embed_batch(missing[start : start + self.batch_size], result)
        return [vector for vector in result if vector is not None]

    def _embed_batch(self, batch: list[tuple[int, str, str]], result: list[list[float] | None]) -> None:
        try:
            data, _, _ = self._client.post(
                "embeddings",
                {"input": [text for _, text, _ in batch], "model": self.model},
                operation="embedding",
                model=self.model,
            )
        except ModelCallError:
            if len(batch) == 1:
                raise
            middle = len(batch) // 2
            self._embed_batch(batch[:middle], result)
            self._embed_batch(batch[middle:], result)
            return
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
