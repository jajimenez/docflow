"""Confluence pages ingestion DAG."""

from datetime import datetime, timedelta

from airflow.sdk import dag, task, Variable

from common import get_db_url


# We place all possible imports in the task functions to keep the DAG parsing fast

RETRIES = 3
RETRY_DELAY = timedelta(minutes=5)

# Name of the Airflow variable holding the list of Confluence targets (JSON)
CONFLUENCE_TARGETS_VAR = "docflow_confluence_targets"


def _get_confluence_options(conn_id: str) -> dict:
    """Resolve the Confluence URL and (optional) credentials from an Airflow connection.

    Each Confluence host/credential set is configured as a separate Airflow connection,
    expected to be configured as follows:

        - Host: host name of the Confluence instance (e.g. "confluence.example.com").
          The full URL may also be provided including the scheme.
        - Schema: URL scheme ("https" by default).
        - Port: port (optional).
        - Login: user name (optional; leave empty for anonymous access).
        - Password: password, API token or empty (optional).
        - Extra (JSON, all optional):
            - "token": personal access token (used instead of login/password).
            - "verify_ssl": whether to verify the TLS certificate (true by default).
            - "cloud": true for Confluence Cloud, false for Server/Data Center
              (false by default).

    Args:
        conn_id: ID of the Airflow connection for this Confluence host.

    Returns:
        Dictionary with the Confluence URL, credentials and options.
    """
    from airflow.sdk import Connection

    conn = Connection.get(conn_id)

    # Build the base URL, following the Airflow HTTP connection convention
    # (scheme://host:port), while also allowing the full URL to be set in the host.
    host = conn.host or ""

    if "://" in host:
        url = host
    else:
        scheme = conn.schema or "https"
        port = f":{conn.port}" if conn.port else ""
        url = f"{scheme}://{host}{port}"

    extra = conn.extra_dejson

    return {
        "base_url": url.rstrip("/"),
        "username": conn.login or None,
        "password": conn.password or None,
        "token": extra.get("token") or None,
        "verify_ssl": extra.get("verify_ssl", True),
        "cloud": extra.get("cloud", False),
    }


@dag(
    dag_id="ingest_confluence_pages",
    start_date=datetime(2026, 1, 1),
    schedule="@daily",  # Re-sync the spaces once a day
    max_active_runs=1,
    catchup=False,
    tags=["docflow", "Confluence"],
)
def ingest_confluence_pages():
    """DAG to ingest the pages of one or more Confluence spaces and process them.

    This DAG ingests every Confluence target configured in the
    "docflow_confluence_targets" Airflow variable, which is a JSON list of objects, each
    with a "conn_id" (the Airflow connection for a Confluence host and its optional
    credentials) and a "space_key". This allows ingesting multiple spaces from multiple
    hosts, each with its own credentials. For example:

        [
            {"conn_id": "confluence_a", "space_key": "ENG"},
            {"conn_id": "confluence_a", "space_key": "OPS"},
            {"conn_id": "confluence_b", "space_key": "DOCS"}
        ]

    Each target is processed independently and in parallel (via dynamic task mapping):
    its pages are fetched, saved to the database and processed (converting the page
    content to text, splitting it into chunks and generating embeddings).

    Authentication is optional per target: if a connection has no credentials, the DAG
    connects to that Confluence host anonymously.
    """

    @task(task_id="set_up_database", retries=RETRIES, retry_delay=RETRY_DELAY)
    def set_up_db():
        """Set up the database."""
        from docflow.db.setup import set_up

        set_up(get_db_url())

    @task(task_id="get_confluence_targets", retries=RETRIES, retry_delay=RETRY_DELAY)
    def get_confluence_targets() -> list[dict]:
        """Read the list of Confluence targets from the Airflow variable.

        Returns:
            List of target objects, each with a "conn_id" and a "space_key".
        """
        targets = Variable.get(
            CONFLUENCE_TARGETS_VAR, default=[], deserialize_json=True
        )

        if not isinstance(targets, list):
            raise ValueError(
                f'"{CONFLUENCE_TARGETS_VAR}" must be a JSON list of targets'
            )

        for t in targets:
            if "conn_id" not in t or "space_key" not in t:
                raise ValueError(
                    'Each Confluence target must have a "conn_id" and a "space_key"'
                )

        return targets

    @task(task_id="save_documents", retries=RETRIES, retry_delay=RETRY_DELAY)
    def save_documents(target: dict) -> dict:
        """Fetch the pages of a Confluence space and save them to the database.

        Args:
            target: Target object with a "conn_id" and a "space_key".

        Returns:
            Object with the target's "conn_id" and the saved "doc_ids", so that the
            processing step can resolve the same host's credentials.
        """
        from docflow.confluence.ingestion import save_document_batch

        options = _get_confluence_options(target["conn_id"])

        doc_ids = save_document_batch(
            get_db_url(),
            space_key=target["space_key"],
            **options,
        )

        return {"conn_id": target["conn_id"], "doc_ids": doc_ids}

    @task(task_id="process_documents", retries=RETRIES, retry_delay=RETRY_DELAY)
    def process_documents(docs: dict):
        """Process the Confluence documents of a target.

        Converts the page content to text, generates embeddings and updates the status
        of each document. The Confluence credentials are resolved from the target's
        connection so that the pages are downloaded from the right host.

        Args:
            docs: Object with the target's "conn_id" and its saved "doc_ids".
        """
        from docflow.confluence.ingestion import process_document_batch

        options = _get_confluence_options(docs["conn_id"])

        process_document_batch(get_db_url(), docs["doc_ids"], **options)

    # Task dependencies. "save_documents" and "process_documents" are dynamically mapped
    # over the list of targets, so each target is handled by its own pair of tasks in
    # parallel.
    db_setup = set_up_db()
    targets = get_confluence_targets()

    db_setup >> targets  # type: ignore

    docs = save_documents.expand(target=targets)
    process_documents.expand(docs=docs)


dag = ingest_confluence_pages()

