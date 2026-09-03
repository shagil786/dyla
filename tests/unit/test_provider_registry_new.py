import asyncio
import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from pydantic import BaseModel

from dyla.compatible import CompatibleEmbeddingProvider, CompatibleModelProvider, normalize_base_url
from dyla.config import Settings, load_settings
from dyla.models import ModelRequest
from dyla.provider_factory import build_provider_bundle, load_plugin


class Answer(BaseModel):
    value: str


def settings(**updates):
    values = dict(
        dyla_model_provider="compatible",
        dyla_auditor_provider="local",
        dyla_embedding_provider="compatible",
        dyla_vector_store="local",
        dyla_web_provider="you",
        model_base_url="https://model.example/v1",
        model_api_key="fake-model-key",
        model_name="model-x",
        embedding_base_url="https://embed.example/v1",
        embedding_api_key="fake-embed-key",
        embedding_model="embed-x",
        you_api_key="fake-you",
        azure_search_vector_dimensions=2,
    )
    values.update(updates)
    return Settings(**values)


def test_settings_reads_provider_neutral_roles(monkeypatch):
    monkeypatch.setenv("DYLA_MODEL_PROVIDER", "compatible")
    monkeypatch.setenv("DYLA_AUDITOR_PROVIDER", "local")
    monkeypatch.setenv("DYLA_EMBEDDING_PROVIDER", "compatible")
    monkeypatch.setenv("DYLA_VECTOR_STORE", "local")
    monkeypatch.setenv("DYLA_WEB_PROVIDER", "you")
    monkeypatch.setenv("MODEL_BASE_URL", "https://model.example/v1")
    monkeypatch.setenv("MODEL_API_KEY", "fake-model")
    monkeypatch.setenv("MODEL_NAME", "model")
    monkeypatch.setenv("EMBEDDING_BASE_URL", "https://embed.example/v1")
    monkeypatch.setenv("EMBEDDING_API_KEY", "fake-embed")
    monkeypatch.setenv("EMBEDDING_MODEL", "embed")
    monkeypatch.setenv("DYLA_EMBEDDING_BATCH_SIZE", "128")
    monkeypatch.setenv("YOU_API_KEY", "fake-you")

    loaded = load_settings()

    assert loaded.dyla_model_provider == "compatible"
    assert loaded.dyla_vector_store == "local"
    assert loaded.model_base_url == "https://model.example/v1"
    assert loaded.embedding_batch_size == 128


def test_normalize_compatible_endpoint_removes_known_operation_suffixes():
    assert normalize_base_url("https://host.example/v1/chat/completions") == "https://host.example/v1"
    assert normalize_base_url("https://host.example/v1/embeddings/") == "https://host.example/v1"
    assert normalize_base_url("https://host.example") == "https://host.example/v1"


def test_compatible_model_uses_normalized_endpoint_and_redacts_key():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(401, text="bad fake-model-key")

    provider = CompatibleModelProvider(
        "https://host.example/v1/chat/completions", "fake-model-key", "model",
        transport=httpx.MockTransport(handler), max_retries=0,
    )
    with pytest.raises(RuntimeError) as error:
        provider.complete(ModelRequest([], None, 10, 0.0))

    assert requests[0].url.path == "/v1/chat/completions"
    assert "fake-model-key" not in str(error.value)
    assert "[REDACTED]" in str(error.value)


def test_compatible_embedding_posts_openai_shape():
    def handler(request):
        assert request.url.path == "/v1/embeddings"
        payload = json.loads(request.content)
        assert payload == {"input": ["one"], "model": "embed"}
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1, 2]}]})

    provider = CompatibleEmbeddingProvider(
        "https://host.example/v1", "fake-embed-key", "embed", transport=httpx.MockTransport(handler)
    )
    assert provider.embed(["one"]) == [[1.0, 2.0]]


def test_compatible_embedding_batches_large_requests_in_input_order():
    requests = []

    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload["input"])
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": index, "embedding": [float(text)]}
                    for index, text in enumerate(payload["input"])
                ]
            },
        )

    provider = CompatibleEmbeddingProvider(
        "https://host.example/v1", "fake-embed-key", "embed",
        transport=httpx.MockTransport(handler), batch_size=256,
    )
    texts = [str(index) for index in range(257)]

    assert provider.embed(texts) == [[float(index)] for index in range(257)]
    assert [len(batch) for batch in requests] == [256, 1]
    assert requests == [texts[:256], texts[256:]]


def test_compatible_embedding_combines_cache_hits_and_results_with_model_namespace(tmp_path):
    calls = []

    def handler(request):
        payload = json.loads(request.content)
        calls.append(payload)
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": index, "embedding": [float(text)]}
                    for index, text in enumerate(payload["input"])
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    cache_path = tmp_path / "embeddings.db"
    first = CompatibleEmbeddingProvider(
        "https://host.example/v1", "fake-embed-key", "embed",
        transport=transport, cache_path=cache_path,
    )
    assert first.embed(["1"]) == [[1.0]]
    assert first.embed(["0", "1", "2"]) == [[0.0], [1.0], [2.0]]
    first.close()

    second = CompatibleEmbeddingProvider(
        "https://host.example/v1", "fake-embed-key", "other-model",
        transport=transport, cache_path=cache_path,
    )
    assert second.embed(["1"]) == [[1.0]]
    second.close()

    assert [call["input"] for call in calls] == [["1"], ["0", "2"], ["1"]]


def test_plugin_loader_imports_module_function():
    loaded = load_plugin(f"{__name__}:plugin", settings())
    assert loaded == "plugin-result"


def plugin(settings):
    return "plugin-result"


def test_compatible_embedding_cache_is_safe_from_async_worker_thread(tmp_path):
    provider = CompatibleEmbeddingProvider(
        "https://host.example/v1",
        "fake-embed-key",
        "embed",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"data": [{"index": 0, "embedding": [1.0, 2.0]}]},
            )
        ),
        cache_path=tmp_path / "embeddings.db",
    )

    try:
        assert asyncio.run(asyncio.to_thread(provider.embed, ["worker text"])) == [[1.0, 2.0]]
    finally:
        provider.close()


def test_compatible_embedding_cache_serializes_concurrent_workers(tmp_path):
    def handler(request):
        text = json.loads(request.content)["input"][0]
        return httpx.Response(
            200,
            json={"data": [{"index": 0, "embedding": [float(len(text))]}]},
        )

    provider = CompatibleEmbeddingProvider(
        "https://host.example/v1",
        "fake-embed-key",
        "embed",
        transport=httpx.MockTransport(handler),
        cache_path=tmp_path / "embeddings.db",
    )

    try:
        texts = [f"worker text {index}" for index in range(12)]
        with ThreadPoolExecutor(max_workers=6) as workers:
            results = list(workers.map(lambda text: provider.embed([text]), texts))

        assert results == [[[float(len(text))]] for text in texts]
    finally:
        provider.close()


def test_factory_composes_configured_roles_and_rejects_unknown_provider():
    bundle = build_provider_bundle(settings())
    assert isinstance(bundle.model, CompatibleModelProvider)
    assert isinstance(bundle.embedding, CompatibleEmbeddingProvider)
    assert bundle.vector_store.__class__.__name__ == "LocalVectorStore"

    with pytest.raises(ValueError, match="unsupported model provider"):
        build_provider_bundle(settings(dyla_model_provider="not-real"))
