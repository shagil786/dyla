"""Application configuration loaded from environment variables."""

from pydantic import AliasChoices, Field, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Service settings for model, web-provider, and vector-store adapters."""

    dyla_model_provider: str = "azure"
    dyla_auditor_provider: str = "local"
    dyla_embedding_provider: str = "azure"
    dyla_vector_store: str = "azure"
    dyla_web_provider: str = "unconfigured"
    model_base_url: str | None = Field(default=None, validation_alias=AliasChoices("DYLA_MODEL_BASE_URL", "MODEL_BASE_URL"))
    model_api_key: str | None = Field(default=None, validation_alias=AliasChoices("DYLA_MODEL_API_KEY", "MODEL_API_KEY"))
    model_name: str | None = Field(default=None, validation_alias=AliasChoices("DYLA_MODEL", "MODEL_NAME"))
    auditor_base_url: str | None = Field(default=None, validation_alias=AliasChoices("DYLA_AUDITOR_BASE_URL", "AUDITOR_BASE_URL"))
    auditor_api_key: str | None = Field(default=None, validation_alias=AliasChoices("DYLA_AUDITOR_API_KEY", "AUDITOR_API_KEY"))
    auditor_model: str | None = Field(default=None, validation_alias=AliasChoices("DYLA_AUDITOR_MODEL", "AUDITOR_MODEL"))
    embedding_base_url: str | None = Field(default=None, validation_alias=AliasChoices("DYLA_EMBEDDING_BASE_URL", "EMBEDDING_BASE_URL"))
    embedding_api_key: str | None = Field(default=None, validation_alias=AliasChoices("DYLA_EMBEDDING_API_KEY", "EMBEDDING_API_KEY"))
    embedding_model: str | None = Field(default=None, validation_alias=AliasChoices("DYLA_EMBEDDING_MODEL", "EMBEDDING_MODEL"))
    azure_openai_endpoint: str | None = None
    azure_openai_api_key: str | None = None
    azure_openai_api_version: str | None = None
    azure_openai_chat_deployment: str | None = None
    azure_openai_embedding_deployment: str | None = None
    azure_search_endpoint: str | None = None
    azure_search_api_key: str | None = None
    azure_search_index: str | None = None
    azure_search_vector_dimensions: int = 1536
    you_api_key: str | None = None
    you_search_endpoint: str = "https://ydc-index.io/v1/search"
    you_contents_endpoint: str = "https://ydc-index.io/v1/contents"

    @model_validator(mode="after")
    def validate_web_provider(self) -> "Settings":
        provider = self.dyla_web_provider.casefold()
        if provider not in {"you", "unconfigured"}:
            raise ValueError("DYLA_WEB_PROVIDER must be 'you' or 'unconfigured'")
        if provider == "you" and not self.you_api_key:
            raise ValueError("YOU_API_KEY is required when DYLA_WEB_PROVIDER=you")
        if self.dyla_model_provider.casefold() == "compatible" and not all((self.model_base_url, self.model_api_key, self.model_name)):
            # Direct construction of legacy Azure settings remains supported for adapters/tests.
            if not all((self.azure_openai_endpoint, self.azure_openai_api_key, self.azure_openai_chat_deployment)):
                raise ValueError("compatible model provider requires model base URL, API key, and model")
        if self.dyla_embedding_provider.casefold() == "compatible" and not all((self.embedding_base_url, self.embedding_api_key, self.embedding_model)):
            raise ValueError("compatible embedding provider requires embedding base URL, API key, and model")
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


def load_settings() -> Settings:
    """Load and validate settings from the environment and optional .env file."""

    try:
        return Settings()
    except ValidationError as exc:
        missing = [
            str(error["loc"][0]).upper()
            for error in exc.errors()
            if error["type"] == "missing"
        ]
        if missing:
            raise ValueError(
                f"Missing required settings: {', '.join(missing)}"
            ) from exc
        raise
