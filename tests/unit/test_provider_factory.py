import pytest

from dyla.auditor import ModelComparator, _TextComparator
from dyla.compatible import CompatibleModelProvider
from dyla.config import Settings
from dyla.provider_factory import build_auditor_provider, build_search_provider
from dyla.web import YouResearchProvider


def settings():
    return Settings(
        azure_openai_endpoint="https://openai.example",
        azure_openai_api_key="fake-openai",
        azure_openai_api_version="2024-10-21",
        azure_openai_chat_deployment="chat",
        azure_openai_embedding_deployment="embed",
        azure_search_endpoint="https://search.example",
        azure_search_api_key="fake-search",
        azure_search_index="evidence",
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


def test_factory_wraps_azure_auditor_in_model_comparator():
    config = settings().model_copy(update={"dyla_auditor_provider": "azure"})

    comparator = build_auditor_provider(config)

    assert isinstance(comparator, ModelComparator)
    assert type(comparator.provider).__name__ == "AzureChatModel"


def test_factory_keeps_text_comparator_for_local_auditor():
    comparator = build_auditor_provider(Settings(dyla_auditor_provider="local"))

    assert isinstance(comparator, _TextComparator)
