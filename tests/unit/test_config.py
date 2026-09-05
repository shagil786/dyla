import pytest

from dyla.config import load_settings


def set_required_env(monkeypatch):
    values = {
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def test_load_settings_reads_you_provider_configuration(monkeypatch):
    set_required_env(monkeypatch)
    monkeypatch.setenv("DYLA_WEB_PROVIDER", "you")
    monkeypatch.setenv("YOU_API_KEY", "fake-you-key")
    monkeypatch.setenv("YOU_SEARCH_ENDPOINT", "https://api.example.invalid/search")
    monkeypatch.setenv("YOU_CONTENTS_ENDPOINT", "https://api.example.invalid/contents")

    settings = load_settings()

    assert settings.dyla_web_provider == "you"
    assert settings.you_api_key == "fake-you-key"
    assert settings.you_search_endpoint.endswith("/search")
    assert settings.you_contents_endpoint.endswith("/contents")


def test_load_settings_reads_auditor_timeout_and_retries_from_env(monkeypatch, tmp_path):
    # Hermetic: pydantic-settings reads .env relative to cwd, so run from a .env-free
    # directory and drop ambient vars for both alias forms before asserting.
    monkeypatch.chdir(tmp_path)
    for var in ("DYLA_AUDITOR_TIMEOUT_SECONDS", "AUDITOR_TIMEOUT_SECONDS", "DYLA_AUDITOR_RETRIES", "AUDITOR_RETRIES"):
        monkeypatch.delenv(var, raising=False)
    set_required_env(monkeypatch)
    monkeypatch.setenv("DYLA_AUDITOR_TIMEOUT_SECONDS", "200")
    monkeypatch.setenv("DYLA_AUDITOR_RETRIES", "5")

    settings = load_settings()

    assert settings.auditor_timeout_seconds == 200.0
    assert settings.auditor_retries == 5


def test_load_settings_reads_unprefixed_auditor_aliases(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for var in ("DYLA_AUDITOR_TIMEOUT_SECONDS", "AUDITOR_TIMEOUT_SECONDS", "DYLA_AUDITOR_RETRIES", "AUDITOR_RETRIES"):
        monkeypatch.delenv(var, raising=False)
    set_required_env(monkeypatch)
    monkeypatch.setenv("AUDITOR_TIMEOUT_SECONDS", "30")
    monkeypatch.setenv("AUDITOR_RETRIES", "0")

    settings = load_settings()

    assert settings.auditor_timeout_seconds == 30.0
    assert settings.auditor_retries == 0


def test_memory_db_path_defaults_to_dyla_db(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for var in ("DYLA_MEMORY_DB_PATH", "MEMORY_DB_PATH"):
        monkeypatch.delenv(var, raising=False)
    set_required_env(monkeypatch)

    settings = load_settings()

    assert settings.memory_db_path == "dyla.db"


def test_load_settings_reads_memory_db_path_from_env(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for var in ("DYLA_MEMORY_DB_PATH", "MEMORY_DB_PATH"):
        monkeypatch.delenv(var, raising=False)
    set_required_env(monkeypatch)
    target = str(tmp_path / "shared" / "memory.db")
    monkeypatch.setenv("DYLA_MEMORY_DB_PATH", target)

    settings = load_settings()

    assert settings.memory_db_path == target


@pytest.mark.parametrize("value", ["0", "-2.5"])
def test_load_settings_rejects_non_positive_auditor_timeout(monkeypatch, tmp_path, value):
    monkeypatch.chdir(tmp_path)
    for var in ("DYLA_AUDITOR_TIMEOUT_SECONDS", "AUDITOR_TIMEOUT_SECONDS"):
        monkeypatch.delenv(var, raising=False)
    set_required_env(monkeypatch)
    monkeypatch.setenv("DYLA_AUDITOR_TIMEOUT_SECONDS", value)

    with pytest.raises(ValueError, match="DYLA_AUDITOR_TIMEOUT_SECONDS must be positive"):
        load_settings()


@pytest.mark.parametrize("value", ["-1", "-3"])
def test_load_settings_rejects_negative_auditor_retries(monkeypatch, tmp_path, value):
    monkeypatch.chdir(tmp_path)
    for var in ("DYLA_AUDITOR_RETRIES", "AUDITOR_RETRIES"):
        monkeypatch.delenv(var, raising=False)
    set_required_env(monkeypatch)
    monkeypatch.setenv("DYLA_AUDITOR_RETRIES", value)

    with pytest.raises(ValueError, match="DYLA_AUDITOR_RETRIES must be non-negative"):
        load_settings()


def test_load_settings_requires_you_api_key_when_you_is_selected(monkeypatch):
    set_required_env(monkeypatch)
    monkeypatch.setenv("DYLA_WEB_PROVIDER", "you")
    monkeypatch.setenv("YOU_API_KEY", "")

    with pytest.raises(ValueError, match="YOU_API_KEY"):
        load_settings()
