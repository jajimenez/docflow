"""Configuration module."""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Docflow settings."""

    # PDF files
    pdf_path: str
    pdf_pending_dir: str
    pdf_processed_dir: str
    pdf_failed_dir: str

    # Docling text extraction models
    extraction_models_path: str

    # Document chunks
    chunk_size: int = 1000
    chunk_overlap: int = 200

    # Ollama embeddings API
    embeddings_api_url: str
    embeddings_api_timeout: int = 30  # API requests timeout in seconds
    embeddings_model: str = "nomic-embed-text:v1.5"
    embeddings_dimension: int = 768

    # Knowledge database
    knowledge_db_url: str

    class Config:
        """Settings metadata."""

        env_file = ".env"
        env_prefix = "DOCFLOW_"


@lru_cache()
def get_settings() -> Settings:
    """Get current settings.

    Returns:
        Settings.
    """
    return Settings()  # type: ignore


settings = get_settings()
