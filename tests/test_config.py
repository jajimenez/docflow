"""Unit tests for docflow.config."""

from pydantic import SecretStr

from docflow.config import Settings


class TestSettings:
    def test_knowledge_db_url_built_from_components(self, monkeypatch):
        monkeypatch.setenv("DOCFLOW_KNOWLEDGE_DB_HOST", "localhost")
        monkeypatch.setenv("DOCFLOW_KNOWLEDGE_DB_USER", "user")
        monkeypatch.setenv("DOCFLOW_KNOWLEDGE_DB_PASSWORD", "password")
        monkeypatch.setenv("DOCFLOW_KNOWLEDGE_DB_NAME", "db")
        monkeypatch.setenv("DOCFLOW_EMBEDDINGS_API_URL", "http://ollama:11434")

        s = Settings()  # type: ignore

        assert (
            s.knowledge_db_url ==
            "postgresql+psycopg://user:password@localhost:5432/db"
        )

    def test_knowledge_db_url_includes_custom_port(self, monkeypatch):
        monkeypatch.setenv("DOCFLOW_KNOWLEDGE_DB_HOST", "localhost")
        monkeypatch.setenv("DOCFLOW_KNOWLEDGE_DB_USER", "user")
        monkeypatch.setenv("DOCFLOW_KNOWLEDGE_DB_PASSWORD", "password")
        monkeypatch.setenv("DOCFLOW_KNOWLEDGE_DB_NAME", "db")
        monkeypatch.setenv("DOCFLOW_KNOWLEDGE_DB_PORT", "5433")
        monkeypatch.setenv("DOCFLOW_EMBEDDINGS_API_URL", "http://ollama:11434")

        s = Settings()  # type: ignore

        assert "localhost:5433" in s.knowledge_db_url

    def test_default_chunk_and_embedding_values(self, monkeypatch):
        monkeypatch.setenv("DOCFLOW_KNOWLEDGE_DB_HOST", "localhost")
        monkeypatch.setenv("DOCFLOW_KNOWLEDGE_DB_USER", "user")
        monkeypatch.setenv("DOCFLOW_KNOWLEDGE_DB_PASSWORD", "password")
        monkeypatch.setenv("DOCFLOW_KNOWLEDGE_DB_NAME", "db")
        monkeypatch.setenv("DOCFLOW_EMBEDDINGS_API_URL", "http://ollama:11434")

        s = Settings()  # type: ignore

        assert s.chunk_size == 1000
        assert s.chunk_overlap == 200
        assert s.embeddings_model == "nomic-embed-text:v1.5"
        assert s.embeddings_dimension == 768
        assert s.mcp_port == 8000
        assert s.knowledge_db_port == 5432
        assert s.embeddings_api_timeout == 30

    def test_mcp_api_key_is_stored_as_secret(self, monkeypatch):
        monkeypatch.setenv("DOCFLOW_KNOWLEDGE_DB_HOST", "localhost")
        monkeypatch.setenv("DOCFLOW_KNOWLEDGE_DB_USER", "user")
        monkeypatch.setenv("DOCFLOW_KNOWLEDGE_DB_PASSWORD", "password")
        monkeypatch.setenv("DOCFLOW_KNOWLEDGE_DB_NAME", "db")
        monkeypatch.setenv("DOCFLOW_EMBEDDINGS_API_URL", "http://ollama:11434")
        monkeypatch.setenv("DOCFLOW_MCP_API_KEY", "api_key")

        s = Settings()  # type: ignore

        assert isinstance(s.mcp_api_key, SecretStr)

        # The raw value must not leak through str()
        assert "api_key" not in str(s.mcp_api_key)
        assert s.mcp_api_key.get_secret_value() == "api_key"

    def test_optional_pdf_dirs_default_to_none(self, monkeypatch):
        monkeypatch.setenv("DOCFLOW_KNOWLEDGE_DB_HOST", "localhost")
        monkeypatch.setenv("DOCFLOW_KNOWLEDGE_DB_USER", "user")
        monkeypatch.setenv("DOCFLOW_KNOWLEDGE_DB_PASSWORD", "password")
        monkeypatch.setenv("DOCFLOW_KNOWLEDGE_DB_NAME", "db")
        monkeypatch.setenv("DOCFLOW_EMBEDDINGS_API_URL", "http://ollama:11434")

        # Clear vars that may be set in the dev container environment
        monkeypatch.delenv("DOCFLOW_PDF_PENDING_DIR", raising=False)
        monkeypatch.delenv("DOCFLOW_PDF_PROCESSED_DIR", raising=False)
        monkeypatch.delenv("DOCFLOW_PDF_FAILED_DIR", raising=False)
        monkeypatch.delenv("DOCFLOW_PDF_EXTRACTION_MODELS_PATH", raising=False)
        monkeypatch.delenv("DOCFLOW_MCP_API_KEY", raising=False)

        s = Settings()  # type: ignore

        assert s.pdf_pending_dir is None
        assert s.pdf_processed_dir is None
        assert s.pdf_failed_dir is None
        assert s.pdf_extraction_models_path is None
        assert s.mcp_api_key is None
