"""Configuration module."""

from functools import lru_cache

from pydantic import SecretStr, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Docflow settings."""

    # PDF files (only required when running PDF ingestion; None is safe for other services)
    pdf_pending_dir: str | None = None
    pdf_processed_dir: str | None = None
    pdf_failed_dir: str | None = None
    pdf_extraction_models_path: str | None = None  # Docling text extraction models

    # Document chunks
    chunk_size: int = 1000
    chunk_overlap: int = 200

    # Ollama embeddings API
    embeddings_api_url: str
    embeddings_api_timeout: int = 30  # API requests timeout in seconds
    embeddings_model: str = "nomic-embed-text:v1.5"
    embeddings_dimension: int = 768

    # MCP server (only required when running the MCP server; None is safe for other services)
    mcp_api_key: SecretStr | None = None
    mcp_port: int = 8000

    # Knowledge database
    knowledge_db_host: str
    knowledge_db_user: str
    knowledge_db_password: str
    knowledge_db_port: int = 5432
    knowledge_db_name: str

    @computed_field
    @property
    def knowledge_db_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.knowledge_db_user}:{self.knowledge_db_password}"
            f"@{self.knowledge_db_host}:{self.knowledge_db_port}/{self.knowledge_db_name}"
        )

    model_config = SettingsConfigDict(env_file=".env", env_prefix="DOCFLOW_")


@lru_cache()
def get_settings() -> Settings:
    """Get current settings.

    Returns:
        Settings.
    """
    return Settings()  # type: ignore


settings = get_settings()
