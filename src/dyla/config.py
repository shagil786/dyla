"""Application configuration loaded from environment variables."""

from pydantic import ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Service settings for model, web-provider, and vector-store adapters."""

    azure_openai_endpoint: str
    azure_openai_api_key: str
    azure_openai_api_version: str
    azure_openai_chat_deployment: str
    azure_openai_embedding_deployment: str
    azure_search_endpoint: str
    azure_search_api_key: str
    azure_search_index: str
    azure_search_vector_dimensions: int = 1536
    dyla_web_provider: str = "unconfigured"
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
