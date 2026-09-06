import asyncio
import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from pydantic import BaseModel

from dyla.compatible import CompatibleEmbeddingProvider, CompatibleModelProvider, normalize_base_url
from dyla.config import Settings, load_settings
from dyla.domain import AnalystAnswer, Citation, Claim
from dyla.models import ModelCallError, ModelRequest
from dyla.provider_factory import build_auditor_provider, build_model_provider, build_provider_bundle, load_plugin


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
    )
    values.update(updates)
    # _env_file=None keeps programmatic construction independent of the developer's
    # local .env (pydantic-settings deep-merges dict-valued fields across sources).
    return Settings(**values, _env_file=None)


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


def test_compatible_embedding_splits_failed_batch_and_returns_all_vectors():
    requests = []

    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload["input"])
        if len(payload["input"]) >= 3:
            return httpx.Response(503, json={"object": "error", "message": "image inputs require VLM serving to be enabled on this server"})
        return httpx.Response(
            200,
            json={"data": [{"index": index, "embedding": [float(text)]} for index, text in enumerate(payload["input"])]},
        )

    provider = CompatibleEmbeddingProvider(
        "https://host.example/v1", "fake-embed-key", "embed",
        transport=httpx.MockTransport(handler), batch_size=4, max_retries=0,
    )
    texts = ["0", "1", "2", "3"]

    assert provider.embed(texts) == [[0.0], [1.0], [2.0], [3.0]]
    # the 4-item batch 503s once, then both 2-item halves succeed independently
    assert requests == [["0", "1", "2", "3"], ["0", "1"], ["2", "3"]]


def test_compatible_embedding_single_item_batch_failure_still_raises():
    requests = []

    def handler(request):
        requests.append(json.loads(request.content)["input"])
        return httpx.Response(503, json={"object": "error", "message": "image inputs require VLM serving to be enabled on this server"})

    provider = CompatibleEmbeddingProvider(
        "https://host.example/v1", "fake-embed-key", "embed", transport=httpx.MockTransport(handler), max_retries=0,
    )

    with pytest.raises(ModelCallError, match="retry exhaustion"):
        provider.embed(["one"])

    assert requests == [["one"]]


def test_compatible_embedding_split_keeps_cache_hits_and_index_mapping(tmp_path):
    calls = []

    def handler(request):
        payload = json.loads(request.content)
        calls.append(payload["input"])
        if len(payload["input"]) > 1:
            return httpx.Response(503, json={"object": "error", "message": "image inputs require VLM serving to be enabled on this server"})
        return httpx.Response(
            200,
            json={"data": [{"index": index, "embedding": [float(text)]} for index, text in enumerate(payload["input"])]},
        )

    provider = CompatibleEmbeddingProvider(
        "https://host.example/v1", "fake-embed-key", "embed",
        transport=httpx.MockTransport(handler), cache_path=tmp_path / "embeddings.db", max_retries=0,
    )
    provider.embed(["1"])  # populate cache
    provider.embed(["3"])
    try:
        assert provider.embed(["1", "2", "3", "4"]) == [[1.0], [2.0], [3.0], [4.0]]
    finally:
        provider.close()

    # cached "1"/"3" are never re-sent; the missing ["2", "4"] batch splits after the 503
    assert calls == [["1"], ["3"], ["2", "4"], ["2"], ["4"]]


def test_compatible_embedding_success_path_sends_exactly_one_request():
    requests = []

    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload["input"])
        return httpx.Response(
            200,
            json={"data": [{"index": index, "embedding": [float(text)]} for index, text in enumerate(payload["input"])]},
        )

    provider = CompatibleEmbeddingProvider(
        "https://host.example/v1", "fake-embed-key", "embed", transport=httpx.MockTransport(handler), max_retries=0,
    )
    texts = ["0", "1", "2"]

    assert provider.embed(texts) == [[0.0], [1.0], [2.0]]
    assert requests == [texts]


def test_compatible_model_posts_base_payload_without_extra_keys():
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}], "usage": {}})

    provider = CompatibleModelProvider(
        "https://host.example/v1", "fake-model-key", "model", transport=httpx.MockTransport(handler)
    )
    provider.complete(ModelRequest([{"role": "user", "content": "hi"}], None, 10, 0.2))

    assert requests == [{"messages": [{"role": "user", "content": "hi"}], "model": "model", "max_tokens": 10, "temperature": 0.2}]


def test_compatible_model_merges_extra_payload_into_request_body():
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}], "usage": {}})

    provider = CompatibleModelProvider(
        "https://host.example/v1", "fake-model-key", "model",
        transport=httpx.MockTransport(handler),
        extra_payload={"chat_template_kwargs": {"thinking": False}},
    )
    provider.complete(ModelRequest([{"role": "user", "content": "hi"}], None, 10, 0.2))

    assert requests[0]["chat_template_kwargs"] == {"thinking": False}
    assert requests[0]["model"] == "model"
    assert requests[0]["max_tokens"] == 10


def test_compatible_model_extracts_json_from_fenced_block():
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "Reasoning first.\n```json\n{\"value\": \"fenced\"}\n```"}}], "usage": {}})

    provider = CompatibleModelProvider("https://host.example/v1", "fake-model-key", "model", transport=httpx.MockTransport(handler))

    response = provider.complete(ModelRequest([{"role": "user", "content": "hi"}], Answer, 10, 0.2))

    assert response.parsed == Answer(value="fenced")


def test_compatible_model_extracts_json_after_think_block():
    content = "<think>Deliberating about { value: fake } and \"quotes\" at length.</think>{\"value\": \"thought-free\"}"

    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}], "usage": {}})

    provider = CompatibleModelProvider("https://host.example/v1", "fake-model-key", "model", transport=httpx.MockTransport(handler))

    response = provider.complete(ModelRequest([{"role": "user", "content": "hi"}], Answer, 10, 0.2))

    assert response.parsed == Answer(value="thought-free")


def test_compatible_model_extracts_balanced_object_from_prose():
    content = "Here is the answer: {\"value\": \"from prose\", \"note\": \"braces { inside } strings\"} — hope that helps."

    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}], "usage": {}})

    provider = CompatibleModelProvider("https://host.example/v1", "fake-model-key", "model", transport=httpx.MockTransport(handler))

    response = provider.complete(ModelRequest([{"role": "user", "content": "hi"}], Answer, 10, 0.2))

    assert response.parsed == Answer(value="from prose")


def test_compatible_model_repairs_truncated_answer_with_whitespace_padding():
    content = (
        '{"answer": "known answer", "claims": [{"id": "c1", "text": "claim text", "citations": []}]'
        + "\n" * 100
    )

    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}], "usage": {}})

    provider = CompatibleModelProvider("https://host.example/v1", "fake-model-key", "model", transport=httpx.MockTransport(handler))

    response = provider.complete(ModelRequest([{"role": "user", "content": "hi"}], AnalystAnswer, 10, 0.2))

    assert response.parsed.answer == "known answer"
    assert response.parsed.limitations == []
    assert response.parsed.claims[0].confidence == "unknown"


def test_compatible_model_prefers_repaired_answer_over_balanced_decoy_object():
    content = (
        '{"answer": "final answer", "claims": [{"id": "c1", "text": "claim text", '
        '"citations": [{"url": "https://example.com/a", "title": "Source", "source_id": "s1", "chunk_id": "c1"}'
        + "\n" * 100
    )

    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}], "usage": {}})

    provider = CompatibleModelProvider("https://host.example/v1", "fake-model-key", "model", transport=httpx.MockTransport(handler))

    response = provider.complete(ModelRequest([{"role": "user", "content": "hi"}], AnalystAnswer, 10, 0.2))

    assert response.parsed.answer == "final answer"
    assert response.parsed.claims[0].citations == [
        Citation(url="https://example.com/a", title="Source", source_id="s1", chunk_id="c1")
    ]
    assert response.parsed.claims[0].confidence == "unknown"


def test_compatible_model_repairs_truncation_inside_string_value():
    content = '{"value": "truncated str'

    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}], "usage": {}})

    provider = CompatibleModelProvider("https://host.example/v1", "fake-model-key", "model", transport=httpx.MockTransport(handler))

    response = provider.complete(ModelRequest([{"role": "user", "content": "hi"}], Answer, 10, 0.2))

    assert response.parsed == Answer(value="truncated str")


def test_compatible_model_repairs_truncated_answer_by_dropping_partial_claims():
    content = (
        '{"answer": "final answer", "claims": ['
        '{"id": "c1", "text": "first claim", "citations": []}, '
        '{"id": "c2", "text": "second cl'
        + "\n" * 100
    )

    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}], "usage": {}})

    provider = CompatibleModelProvider("https://host.example/v1", "fake-model-key", "model", transport=httpx.MockTransport(handler))

    response = provider.complete(ModelRequest([{"role": "user", "content": "hi"}], AnalystAnswer, 10, 0.2))

    assert response.parsed.answer == "final answer"
    assert response.parsed.claims == [Claim(id="c1", text="first claim", citations=[])]
    assert response.parsed.limitations == []


def test_compatible_model_prefers_drop_repaired_answer_over_balanced_first_claim_object():
    content = (
        '{"answer": "final answer", "claims": ['
        '{"answer": "decoy claim", "claims": [], "id": "c1", "text": "first claim", "citations": []}, '
        '{"id": "c2", "text": "second cl'
        + "\n" * 100
    )

    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}], "usage": {}})

    provider = CompatibleModelProvider("https://host.example/v1", "fake-model-key", "model", transport=httpx.MockTransport(handler))

    response = provider.complete(ModelRequest([{"role": "user", "content": "hi"}], AnalystAnswer, 10, 0.2))

    assert response.parsed.answer == "final answer"
    assert response.parsed.claims == [Claim(id="c1", text="first claim", citations=[])]


def test_compatible_model_raises_when_answer_value_truncation_is_unrecoverable():
    content = '{"answer": "cut off mid sent'

    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}], "usage": {}})

    provider = CompatibleModelProvider(
        "https://host.example/v1", "fake-model-key", "model",
        transport=httpx.MockTransport(handler), max_retries=0,
    )

    with pytest.raises(RuntimeError, match="malformed chat response") as error:
        provider.complete(ModelRequest([{"role": "user", "content": "hi"}], AnalystAnswer, 10, 0.2))

    assert "fake-model-key" not in str(error.value)


def test_compatible_model_raises_when_truncated_content_is_unrepairable():
    content = '{"value": not json'

    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}], "usage": {}})

    provider = CompatibleModelProvider(
        "https://host.example/v1", "fake-model-key", "model",
        transport=httpx.MockTransport(handler), max_retries=0,
    )

    with pytest.raises(RuntimeError, match="malformed chat response") as error:
        provider.complete(ModelRequest([{"role": "user", "content": "hi"}], Answer, 10, 0.2))

    assert "fake-model-key" not in str(error.value)


def test_compatible_model_raises_when_no_json_is_extractable():
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "plain prose with no structure"}}], "usage": {}})

    provider = CompatibleModelProvider(
        "https://host.example/v1", "fake-model-key", "model",
        transport=httpx.MockTransport(handler), max_retries=0,
    )

    with pytest.raises(RuntimeError, match="malformed chat response") as error:
        provider.complete(ModelRequest([{"role": "user", "content": "hi"}], Answer, 10, 0.2))

    assert "fake-model-key" not in str(error.value)


def test_settings_parse_extra_payload_json_from_env(monkeypatch, tmp_path):
    # Hermetic: pydantic-settings reads .env relative to cwd and deep-merges dict fields,
    # so run from a .env-free directory and drop ambient payload vars for both alias forms.
    monkeypatch.chdir(tmp_path)
    for var in ("DYLA_MODEL_EXTRA_PAYLOAD", "MODEL_EXTRA_PAYLOAD", "DYLA_AUDITOR_EXTRA_PAYLOAD", "AUDITOR_EXTRA_PAYLOAD"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("DYLA_MODEL_EXTRA_PAYLOAD", '{"chat_template_kwargs": {"thinking": false}}')
    monkeypatch.setenv("DYLA_AUDITOR_EXTRA_PAYLOAD", '{"seed": 7}')

    loaded = load_settings()

    assert loaded.model_extra_payload == {"chat_template_kwargs": {"thinking": False}}
    assert loaded.auditor_extra_payload == {"seed": 7}

    monkeypatch.setenv("DYLA_MODEL_EXTRA_PAYLOAD", "")
    assert load_settings().model_extra_payload is None


def test_factory_passes_extra_payload_to_model_and_auditor_providers(monkeypatch):
    # Drop ambient payload vars (both alias forms) so the explicit kwargs are the sole source.
    for var in ("DYLA_MODEL_EXTRA_PAYLOAD", "MODEL_EXTRA_PAYLOAD", "DYLA_AUDITOR_EXTRA_PAYLOAD", "AUDITOR_EXTRA_PAYLOAD"):
        monkeypatch.delenv(var, raising=False)
    model = build_model_provider(settings(model_extra_payload={"chat_template_kwargs": {"thinking": False}}))
    auditor = build_auditor_provider(settings(dyla_auditor_provider="compatible", auditor_extra_payload={"seed": 7}))

    assert model.extra_payload == {"chat_template_kwargs": {"thinking": False}}
    assert auditor.provider.extra_payload == {"seed": 7}


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


def test_compatible_model_retries_connection_errors_then_succeeds():
    """A transient ConnectError is the same class of failure as a timeout and
    gets the same retry-with-backoff, not an immediate abort."""
    attempts = []

    def handler(request):
        attempts.append(1)
        if len(attempts) == 1:
            raise httpx.ConnectError("connection reset by peer", request=request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}},
        )

    provider = CompatibleModelProvider(
        "https://host.example/v1", "fake-key", "model",
        transport=httpx.MockTransport(handler), max_retries=1, sleeper=lambda _seconds: None,
    )
    response = provider.complete(ModelRequest([], None, 10, 0.0))

    assert len(attempts) == 2
    assert response.text == "ok"


def test_compatible_model_reports_connection_error_after_retry_exhaustion():
    attempts = []

    def handler(request):
        attempts.append(1)
        raise httpx.ConnectError("connection reset by peer", request=request)

    provider = CompatibleModelProvider(
        "https://host.example/v1", "fake-key", "model",
        transport=httpx.MockTransport(handler), max_retries=2, sleeper=lambda _seconds: None,
    )
    with pytest.raises(ModelCallError) as error:
        provider.complete(ModelRequest([], None, 10, 0.0))

    assert len(attempts) == 3, "max_retries was not used for a connection error"
    assert "connection error" in str(error.value)
