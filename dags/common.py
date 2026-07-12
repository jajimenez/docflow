"""Shared helpers for the Docflow DAGs.

This module holds Airflow-specific helpers used by more than one DAG. It lives next to
the DAGs (and not in the ``docflow`` package) because the ``docflow`` package is
intentionally Airflow-agnostic.
"""

import os

# ID of the Airflow connection holding the knowledge database credentials
KNOWLEDGE_DB_CONN_ID = "knowledge_db"

# Maximum number of documents processed concurrently by a dynamically mapped processing
# task within a single DAG run. Shared by the ingestion DAGs to cap the load on the CPU
# (PDF extraction) and the embeddings API. Configurable via the
# "DOCFLOW_MAX_ACTIVE_PROCESSING_TASKS" environment variable.
MAX_ACTIVE_PROCESSING_TASKS = int(
    os.environ.get("DOCFLOW_MAX_ACTIVE_PROCESSING_TASKS", "4")
)


def get_db_url() -> str:
    """Build the knowledge database URL from its Airflow connection.

    Returns:
        Knowledge Database URL.
    """
    from airflow.sdk import Connection

    conn = Connection.get(KNOWLEDGE_DB_CONN_ID)

    return (
        f"postgresql+psycopg://{conn.login}:{conn.password}"
        f"@{conn.host}:{conn.port}/{conn.schema}"
    )
