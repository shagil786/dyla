import pytest

from dyla.config import load_settings


def test_load_settings_reads_required_environment(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://openai.example")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
    monkeypatch.setenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "chat")
    monkeypatch.setenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "embed")
    monkeypatch.setenv("AZURE_SEARCH_ENDPOINT", "https://search.example")
    monkeypatch.setenv("AZURE_SEARCH_API_KEY", "search-key")
    monkeypatch.setenv("AZURE_SEARCH_INDEX", "dyla-evidence")

    settings = load_settings()

    assert settings.azure_openai_chat_deployment == "chat"
    assert settings.azure_search_index == "dyla-evidence"


def test_load_settings_rejects_missing_secret(monkeypatch):
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="AZURE_OPENAI_API_KEY"):
        load_settings()
