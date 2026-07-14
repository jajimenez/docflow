"""Pytest configuration and shared fixtures.

Environment variables are set at module level so they are available before any Docflow
module is imported (pydantic-settings reads them at class instantiation time).
"""

import os

# --------------------------------------------------------------------------------------
# Required settings — set defaults so the Settings object can be built without a real
# .env file or any running external service.
# --------------------------------------------------------------------------------------
os.environ.setdefault(
    "DOCFLOW_EMBEDDINGS_API_URL",
    "http://localhost:11434/api/embeddings",
)

os.environ.setdefault("DOCFLOW_KNOWLEDGE_DB_HOST", "localhost")
os.environ.setdefault("DOCFLOW_KNOWLEDGE_DB_USER", "test_user")
os.environ.setdefault("DOCFLOW_KNOWLEDGE_DB_PASSWORD", "test_password")
os.environ.setdefault("DOCFLOW_KNOWLEDGE_DB_NAME", "test_db")
