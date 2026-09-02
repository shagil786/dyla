import json
import sqlite3

import httpx
import pytest
from pydantic import BaseModel

from dyla.azure_models import AzureChatModel, AzureEmbeddingModel
from dyla.config import Settings
from dyla.models import ModelCallError, ModelRequest


class Answer(BaseModel):
    answer: str
    confidence: float


def settings():
    return Settings(
        azure_openai_endpoint="https://azure.example",
        azure_openai_api_key="super-secret-key",
        azure_openai_api_version="2024-10-21",
        azure_openai_chat_deployment="chat-deployment",
        azure_openai_embedding_deployment="embedding-deployment",
        azure_search_endpoint="https://search.example",
        azure_search_api_key="search-key",
        azure_search_index="evidence",
    )


def test_chat_model_parses_structured_output_and_usage_without_leaking_secret():
    requests = []

    def handler(request: httpx.Request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"answer":"grounded","confidence":0.9}'}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 7},
            },
        )

    model = AzureChatModel(settings(), transport=httpx.MockTransport(handler))

    response = model.complete(
        ModelRequest(
            messages=[{"role": "user", "content": "answer"}],
            response_schema=Answer,
            max_tokens=100,
            temperature=0.2,
        )
    )

    assert response.parsed == Answer(answer="grounded", confidence=0.9)
    assert response.text == '{"answer":"grounded","confidence":0.9}'
    assert (response.input_tokens, response.output_tokens) == (12, 7)
    assert requests[0].headers["api-key"] == "super-secret-key"
    assert "super-secret-key" not in repr(response)


def test_embedding_model_batches_inputs_and_caches_unchanged_text(tmp_path):
    calls = []

    def handler(request: httpx.Request):
        payload = json.loads(request.content)
        calls.append(payload["input"])
        return httpx.Response(
            200,
            json={"data": [{"index": i, "embedding": [float(i), 1.0]} for i in range(len(payload["input"]))]},
        )

    model = AzureEmbeddingModel(
        settings(),
        transport=httpx.MockTransport(handler),
        cache_path=tmp_path / "embeddings.db",
        batch_size=2,
    )

    assert model.embed(["alpha", "beta", "gamma"]) == [[0.0, 1.0], [1.0, 1.0], [0.0, 1.0]]
    assert model.embed(["alpha", "beta", "gamma"]) == [[0.0, 1.0], [1.0, 1.0], [0.0, 1.0]]
    assert calls == [["alpha", "beta"], ["gamma"]]


def test_transient_status_is_retried_with_bounded_backoff():
    attempts = 0
    delays = []

    def handler(request: httpx.Request):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(503, text="temporary outage")
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}], "usage": {}})

    model = AzureChatModel(
        settings(),
        transport=httpx.MockTransport(handler),
        max_retries=2,
        sleeper=delays.append,
        backoff_base=0.1,
    )

    assert model.complete(ModelRequest([{"role": "user", "content": "hi"}], None, 10, 0.0)).text == "ok"
    assert attempts == 3
    assert delays == [0.1, 0.2]


def test_chat_telemetry_includes_pricing_retry_status_and_cost():
    def handler(request: httpx.Request):
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 1000, "completion_tokens": 500},
            },
        )

    model = AzureChatModel(
        settings(),
        transport=httpx.MockTransport(handler),
        input_cost_per_1k=0.01,
        output_cost_per_1k=0.02,
        model_name="gpt-test",
    )

    response = model.complete(ModelRequest([], None, 10, 0.0))

    assert response.deployment == "chat-deployment"
    assert response.model == "gpt-test"
    assert response.retry_count == 0
    assert response.status_code == 200
    assert response.estimated_cost == 0.02
    assert response.latency_ms >= 0


def test_retry_after_429_is_counted_and_attempts_are_bounded():
    attempts = 0
    delays = []

    def handler(request: httpx.Request):
        nonlocal attempts
        attempts += 1
        return httpx.Response(200 if attempts == 2 else 429, json={"choices": [{"message": {"content": "ok"}}], "usage": {}})

    model = AzureChatModel(
        settings(), transport=httpx.MockTransport(handler), max_retries=1,
        sleeper=delays.append, backoff_base=0.1,
    )

    response = model.complete(ModelRequest([], None, 10, 0.0))

    assert response.text == "ok"
    assert response.retry_count == 1
    assert attempts == 2
    assert delays == [0.1]


def test_retry_exhaustion_raises_error_with_telemetry_and_bounded_attempts():
    attempts = 0
    delays = []

    def handler(request: httpx.Request):
        nonlocal attempts
        attempts += 1
        return httpx.Response(429, text="rate limited")

    model = AzureChatModel(
        settings(), transport=httpx.MockTransport(handler), max_retries=2,
        sleeper=delays.append, backoff_base=0.1,
    )

    try:
        model.complete(ModelRequest([], None, 10, 0.0))
    except RuntimeError as exc:
        assert attempts == 3
        assert delays == [0.1, 0.2]
        assert exc.telemetry.retry_count == 2
        assert exc.telemetry.status_code == 429
        assert exc.telemetry.error == "retry exhaustion"
        assert exc.telemetry.latency_ms >= 0
    else:
        raise AssertionError("expected retry exhaustion")


def test_embedding_cache_is_namespaced_by_deployment(tmp_path):
    calls = []

    def handler(request: httpx.Request):
        payload = json.loads(request.content)
        calls.append(request.url.path)
        vector_value = 1.0 if "embedding-deployment" in request.url.path else 2.0
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [vector_value]}]})

    first = AzureEmbeddingModel(settings(), transport=httpx.MockTransport(handler), cache_path=tmp_path / "cache.db")
    assert first.embed(["same content"]) == [[1.0]]
    first.close()

    second_settings = settings()
    second_settings.azure_openai_embedding_deployment = "other-deployment"
    second = AzureEmbeddingModel(second_settings, transport=httpx.MockTransport(handler), cache_path=tmp_path / "cache.db")
    assert second.embed(["same content"]) == [[2.0]]
    assert len(calls) == 2
    second.close()


def test_adapters_close_http_and_sqlite_resources_and_support_context_manager(tmp_path):
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"data": []}))
    with AzureEmbeddingModel(settings(), transport=transport, cache_path=tmp_path / "cache.db") as model:
        assert model._cache is not None
    assert model._cache is None

    chat = AzureChatModel(settings(), transport=transport)
    chat.close()
    assert chat._client.client.is_closed


@pytest.mark.parametrize(
    "body, expected_error",
    [
        ("not-json", "invalid JSON response"),
        ('{"choices": []}', "malformed chat response"),
        ('{"choices": [{"message": {"content": "{\\"wrong\\": true}"}}]}', "response validation failed"),
    ],
)
def test_malformed_chat_responses_raise_consistent_telemetry_error(body, expected_error):
    def handler(request: httpx.Request):
        return httpx.Response(200, content=body)

    model = AzureChatModel(
        settings(), transport=httpx.MockTransport(handler), model_name="gpt-test",
        input_cost_per_1k=0.01, output_cost_per_1k=0.02,
    )

    with pytest.raises(ModelCallError, match=expected_error) as caught:
        model.complete(ModelRequest([], Answer, 10, 0.0))

    telemetry = caught.value.telemetry
    assert telemetry.deployment == "chat-deployment"
    assert telemetry.model == "gpt-test"
    assert telemetry.status_code == 200
    assert telemetry.retry_count == 0
    assert telemetry.input_tokens == telemetry.output_tokens == 0
    assert telemetry.estimated_cost == 0
    assert telemetry.input_cost_per_1k == 0.01
    assert telemetry.output_cost_per_1k == 0.02
    assert telemetry.latency_ms >= 0
    assert "super-secret-key" not in str(caught.value)
    assert "super-secret-key" not in telemetry.error


def test_legacy_embedding_cache_schema_fails_with_clear_compatibility_error(tmp_path):
    database = tmp_path / "legacy.db"
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE embedding_cache (content_hash TEXT PRIMARY KEY, embedding_json TEXT NOT NULL)"
    )
    connection.commit()
    connection.close()

    with pytest.raises(RuntimeError, match="legacy content_hash schema"):
        AzureEmbeddingModel(settings(), cache_path=database)


def test_secret_is_redacted_from_adapter_errors():
    def handler(request: httpx.Request):
        return httpx.Response(401, text="invalid super-secret-key")

    model = AzureChatModel(settings(), transport=httpx.MockTransport(handler), max_retries=0)

    try:
        model.complete(ModelRequest([], None, 10, 0.0))
    except RuntimeError as exc:
        assert "super-secret-key" not in str(exc)
        assert "[REDACTED]" in str(exc)
    else:
        raise AssertionError("expected adapter failure")
