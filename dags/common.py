"""Shared helpers for the Docflow DAGs.

This module holds Airflow-specific helpers used by more than one DAG. It lives next to
the DAGs (and not in the ``docflow`` package) because the ``docflow`` package is
intentionally Airflow-agnostic.
"""

# ID of the Airflow connection holding the knowledge database credentials
KNOWLEDGE_DB_CONN_ID = "knowledge_db"


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
