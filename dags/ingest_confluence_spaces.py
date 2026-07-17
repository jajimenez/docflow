"""Confluence spaces ingestion DAG."""

from datetime import datetime, timedelta

from airflow.sdk import dag, task, Variable

from common import get_db_url, MAX_ACTIVE_PROCESSING_TASKS


# We place all possible imports in the task functions to keep the DAG parsing fast

RETRIES = 3
RETRY_DELAY = timedelta(minutes=5)

# Name of the Airflow variable holding the list of Confluence targets (JSON)
CONFLUENCE_TARGETS_VAR = "confluence_targets"


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
    host = conn.host or ""

    if "://" in host:
        # Full URL is provided
        url = host
    else:
        # Build the URL
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
    dag_id="ingest_confluence_spaces",
    start_date=datetime(2026, 1, 1),
    schedule="@daily",  # Re-sync the spaces once a day
    max_active_runs=1,
    catchup=False,
    tags=["docflow", "Confluence"],
)
def ingest_confluence_spaces():
    """DAG to ingest the pages of one or more Confluence spaces.

    This DAG ingests every Confluence target configured in the "confluence_targets"
    Airflow variable, which is a JSON list of objects, each with a "conn_id" (the
    Airflow connection for a Confluence host and its optional credentials) and a
    "space_key". This allows ingesting multiple spaces from multiple hosts, each with
    its own credentials. For example:

        [
            {"conn_id": "confluence_host_1", "space_key": "a"},
            {"conn_id": "confluence_host_2", "space_key": "b"},
            {"conn_id": "confluence_host_3", "space_key": "c"}
        ]

    All the pages of all targets/spaces are fetched and saved to the database as
    documents. The saved pages are then flattened into a single list and processed in
    parallel, one mapped task instance per page (using dynamic task mapping) (converting
    the page text (which is in HTML format) to Markdown text, splitting it into chunks,
    and generating their embeddings), giving per-page success/failure tracking and
    independent retries.

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
        """Fetch the pages of a Confluence space and save them to the database as
        documents.

        Args:
            target: Target object with a "conn_id" and a "space_key".

        Returns:
            Object with the target's "conn_id" and the saved "doc_ids", so that the
            processing step can resolve the same space's credentials.
        """
        from docflow.confluence.ingestion import save_document_batch

        options = _get_confluence_options(target["conn_id"])

        doc_ids = save_document_batch(
            get_db_url(),
            space_key=target["space_key"],
            **options,
        )

        return {"conn_id": target["conn_id"], "doc_ids": doc_ids}

    @task(task_id="flatten_documents", retries=RETRIES, retry_delay=RETRY_DELAY)
    def flatten_documents(docs: list[dict]) -> list[dict]:
        """Flatten the per-space documents into a flat list of documents.

        Airflow cannot map a task directly over the per-instance output of another
        mapped task, so the saved documents of every space are collected here into a
        single flat list, one object per document, so that the processing step can be
        mapped over individual documents.

        Args:
            docs: One object per space, each with a "conn_id" and its saved "doc_ids".

        Returns:
            One object per document, each with a "conn_id" and a single "doc_id".
        """
        return [
            {"conn_id": d["conn_id"], "doc_id": doc_id}
            for d in docs
            for doc_id in d["doc_ids"]
        ]

    @task(
        task_id="process_document",
        retries=RETRIES,
        retry_delay=RETRY_DELAY,
        max_active_tis_per_dagrun=MAX_ACTIVE_PROCESSING_TASKS,
    )
    def process_document(doc: dict):
        """Process a Confluence document.

        Downloads the document (Confluence page) text (which is in HTML format),
        converts it to Markdown text, splits it into chunks, generates their embeddings,
        and updates the status of the document. The Confluence credentials are resolved
        from the document's connection so that the document (page) text is downloaded
        from the right host. This task is dynamically mapped over the flattened
        documents, so each document is processed by its own task instance, giving
        per-document success/failure tracking and independent retries.

        Args:
            doc: Object with the document's "conn_id" and "doc_id".
        """
        from docflow.confluence import ingestion

        options = _get_confluence_options(doc["conn_id"])
        ingestion.process_document(get_db_url(), doc["doc_id"], **options)

    # Task dependencies
    db_setup = set_up_db()
    targets = get_confluence_targets()

    db_setup >> targets  # type: ignore

    docs_by_space = save_documents.expand(target=targets)  # type: ignore
    docs = flatten_documents(docs_by_space)  # type: ignore
    process_document.expand(doc=docs)  # type: ignore


dag = ingest_confluence_spaces()
