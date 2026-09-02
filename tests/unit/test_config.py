import pytest

from dyla.config import load_settings


def set_required_azure(monkeypatch):
    values = {
        "AZURE_OPENAI_ENDPOINT": "https://openai.example.invalid",
        "AZURE_OPENAI_API_KEY": "fake-openai-key",
        "AZURE_OPENAI_API_VERSION": "2024-10-21",
        "AZURE_OPENAI_CHAT_DEPLOYMENT": "fake-chat",
        "AZURE_OPENAI_EMBEDDING_DEPLOYMENT": "fake-embed",
        "AZURE_SEARCH_ENDPOINT": "https://search.example.invalid",
        "AZURE_SEARCH_API_KEY": "fake-search-key",
        "AZURE_SEARCH_INDEX": "dyla-evidence",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def test_load_settings_reads_you_provider_configuration(monkeypatch):
    set_required_azure(monkeypatch)
    monkeypatch.setenv("DYLA_WEB_PROVIDER", "you")
    monkeypatch.setenv("YOU_API_KEY", "fake-you-key")
    monkeypatch.setenv("YOU_SEARCH_ENDPOINT", "https://api.example.invalid/search")
    monkeypatch.setenv("YOU_CONTENTS_ENDPOINT", "https://api.example.invalid/contents")

    settings = load_settings()

    assert settings.dyla_web_provider == "you"
    assert settings.you_api_key == "fake-you-key"
    assert settings.you_search_endpoint.endswith("/search")
    assert settings.you_contents_endpoint.endswith("/contents")


def test_load_settings_requires_you_api_key_when_you_is_selected(monkeypatch):
    set_required_azure(monkeypatch)
    monkeypatch.setenv("DYLA_WEB_PROVIDER", "you")
    monkeypatch.setenv("YOU_API_KEY", "")

    with pytest.raises(ValueError, match="YOU_API_KEY"):
        load_settings()
