import httpx
import pytest

from dyla.auditor import ModelComparator, _TextComparator
from dyla.compatible import (
    CompatibleModelProvider,
    LocalEmbeddingProvider,
    LocalModelProvider,
)
from dyla.config import Settings, load_settings
from dyla.local_vector import LocalVectorStore
from dyla.models import ModelRequest
from dyla.provider_factory import (
    build_auditor_provider,
    build_embedding_provider,
    build_model_provider,
    build_search_provider,
    build_vector_store,
)
from dyla.web import YouResearchProvider


def settings():
    return Settings(
        dyla_web_provider="you",
        you_api_key="fake-you",
        you_search_endpoint="https://api.example/search",
        you_contents_endpoint="https://api.example/contents",
    )


def test_build_search_provider_constructs_you_adapter_from_settings():
    provider = build_search_provider(settings(), resolver=lambda host, port: [(None, None, None, None, ("93.184.216.34", 443))])

    assert isinstance(provider, YouResearchProvider)
    assert provider.search_endpoint == "https://api.example/search"
    assert provider.contents_endpoint == "https://api.example/contents"


def test_build_search_provider_rejects_unconfigured_provider():
    config = settings().model_copy(update={"dyla_web_provider": "unconfigured"})

    with pytest.raises(ValueError, match="web provider"):
        build_search_provider(config)


def test_factory_wraps_compatible_auditor_in_model_comparator():
    config = Settings(
        dyla_auditor_provider="compatible",
        auditor_base_url="https://judge.example/v1",
        auditor_api_key="fake-judge",
        auditor_model="judge-x",
    )

    comparator = build_auditor_provider(config)

    assert isinstance(comparator, ModelComparator)
    assert isinstance(comparator.provider, CompatibleModelProvider)
    assert comparator.provider.model == "judge-x"



def test_factory_keeps_text_comparator_for_local_auditor():
    comparator = build_auditor_provider(Settings(dyla_auditor_provider="local"))

    assert isinstance(comparator, _TextComparator)


# ---------------------------------------------------------------------------
# Provider independence: a fresh checkout configures itself without credentials,
# any OpenAI-compatible endpoint works as a model runner, and no vendor name
# is magic anywhere in the factory.
# ---------------------------------------------------------------------------

_PROVIDER_ENV_VARS = (
    "DYLA_MODEL_PROVIDER",
    "DYLA_AUDITOR_PROVIDER",
    "DYLA_EMBEDDING_PROVIDER",
    "DYLA_VECTOR_STORE",
    "DYLA_WEB_PROVIDER",
)


def _clean_provider_env(monkeypatch, tmp_path):
    # Hermetic: pydantic-settings reads .env relative to cwd, so run from a
    # .env-free directory and drop ambient role selections before asserting.
    monkeypatch.chdir(tmp_path)
    for var in _PROVIDER_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def test_fresh_checkout_defaults_every_model_role_to_local(monkeypatch, tmp_path):
    _clean_provider_env(monkeypatch, tmp_path)

    settings = load_settings()

    assert settings.dyla_model_provider == "local"
    assert settings.dyla_auditor_provider == "local"
    assert settings.dyla_embedding_provider == "local"
    assert settings.dyla_vector_store == "local"
    # There is no local web: search stays explicitly unconfigured rather than
    # pointing at a provider nobody has credentials for.
    assert settings.dyla_web_provider == "unconfigured"


def test_default_settings_build_all_local_providers_without_secrets(monkeypatch, tmp_path):
    """The local fallback for every role constructs with zero secrets set."""
    _clean_provider_env(monkeypatch, tmp_path)
    for var in (
        "DYLA_MODEL_API_KEY", "MODEL_API_KEY",
        "DYLA_AUDITOR_API_KEY", "AUDITOR_API_KEY",
        "DYLA_EMBEDDING_API_KEY", "EMBEDDING_API_KEY",
        "QDRANT_URL", "QDRANT_API_KEY", "YOU_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    settings = load_settings()

    model = build_model_provider(settings)
    auditor = build_auditor_provider(settings)
    embedding = build_embedding_provider(settings)
    vector_store = build_vector_store(settings, embedder=embedding)

    assert isinstance(model, LocalModelProvider)
    assert isinstance(auditor, _TextComparator)
    assert isinstance(embedding, LocalEmbeddingProvider)
    assert isinstance(vector_store, LocalVectorStore)
    # And they run without touching the network: pure-Python, no transport.
    assert model.complete(ModelRequest([], None, 10, 0.0)).model == "local"
    assert embedding.embed(["hello"]) == [[float(sum(b"hello")) % 997, 5.0]]


def test_compatible_model_posts_standard_shape_to_any_local_runner():
    """Any model runner speaking /v1/chat/completions works — here an
    Ollama-style localhost endpoint. No vendor-specific URL, header, or
    payload key anywhere in the request."""
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["payload"] = request.content.decode()
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}}],
                  "usage": {"prompt_tokens": 3, "completion_tokens": 1}},
        )

    provider = CompatibleModelProvider(
        "http://localhost:11434", "ollama-has-no-key-but-the-field-is-required",
        "llama3",
        transport=httpx.MockTransport(handler), max_retries=0,
    )
    response = provider.complete(ModelRequest(
        [{"role": "user", "content": "hi"}], None, 10, 0.0))

    import json

    assert seen["url"] == "http://localhost:11434/v1/chat/completions"
    payload = json.loads(seen["payload"])
    assert payload["model"] == "llama3"
    assert payload["messages"] == [{"role": "user", "content": "hi"}]
    assert set(payload) == {"messages", "model", "max_tokens", "temperature"}
    assert (response.input_tokens, response.output_tokens) == (3, 1)


@pytest.mark.parametrize("vendor", ["groq", "azure", "openai", "anthropic", "together"])
def test_vendor_names_are_not_magic_model_providers(vendor):
    """No hardcoded external LLM API: a vendor name is just an unknown string."""
    with pytest.raises(ValueError, match="unsupported model provider"):
        build_model_provider(Settings(dyla_model_provider=vendor, _env_file=None))


@pytest.mark.parametrize(
    "build, role, value",
    [
        ("auditor", "auditor provider", "groq"),
        ("embedding", "embedding provider", "voyage"),
        ("vector_store", "vector store", "pinecone"),
    ],
)
def test_unknown_providers_are_rejected_for_every_role(build, role, value):
    builders = {
        "auditor": build_auditor_provider,
        "embedding": build_embedding_provider,
        "vector_store": build_vector_store,
    }
    field = {
        "auditor": "dyla_auditor_provider",
        "embedding": "dyla_embedding_provider",
        "vector_store": "dyla_vector_store",
    }[build]
    with pytest.raises(ValueError, match=role):
        builders[build](Settings(**{field: value}, _env_file=None))


def test_unknown_web_provider_is_rejected_at_settings_validation():
    """The web role has no local adapter, so unknown values fail fast at
    config load — before any provider is built."""
    with pytest.raises(ValueError, match="DYLA_WEB_PROVIDER must be"):
        Settings(dyla_web_provider="brave", _env_file=None)
