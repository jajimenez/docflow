"""Azure DevOps wikis ingestion DAG."""

from datetime import datetime, timedelta

from airflow.sdk import dag, task, Variable

from common import get_db_url, MAX_ACTIVE_PROCESSING_TASKS


# We place all possible imports in the task functions to keep the DAG parsing fast

RETRIES = 3
RETRY_DELAY = timedelta(minutes=5)

# Name of the Airflow variable holding the list of Azure DevOps targets (JSON)
AZURE_DEVOPS_TARGETS_VAR = "azure_devops_targets"


def _get_azure_devops_options(conn_id: str) -> dict:
    """Resolve the Azure DevOps organization URL and PAT from an Airflow connection.

    Each Azure DevOps organization is configured as a separate Airflow connection,
    expected to be configured as follows:

        - Host: hostname of the Azure DevOps organization. For cloud instances, this is
          ``dev.azure.com/{org}`` (e.g. ``dev.azure.com/org``). The full URL may also
          be provided including the scheme.
        - Schema: URL scheme (``"https"`` by default).
        - Password: Personal Access Token (PAT).

    Args:
        conn_id: ID of the Airflow connection for this Azure DevOps organization.

    Returns:
        Dictionary with the organization URL and PAT.
    """
    from airflow.sdk import Connection

    conn = Connection.get(conn_id)
    host = conn.host or ""

    if "://" in host:
        # Full URL is provided
        org_url = host
    else:
        # Build the URL
        scheme = conn.schema or "https"
        org_url = f"{scheme}://{host}"

    return {
        "org_url": org_url.rstrip("/"),
        "pat": conn.password or None,
    }


@dag(
    dag_id="ingest_azure_devops_wikis",
    start_date=datetime(2026, 1, 1),
    schedule="@daily",  # Re-sync the wikis once a day
    max_active_runs=1,
    catchup=False,
    tags=["docflow", "Azure DevOps"],
)
def ingest_azure_devops_wikis():
    """DAG to ingest the pages of one or more Azure DevOps wikis.

    This DAG ingests every Azure DevOps target configured in the "azure_devops_targets"
    Airflow variable, which is a JSON list of objects, each with a "conn_id" (the
    Airflow connection for an Azure DevOps organization and its PAT), a "project" and a
    "wiki". This allows ingesting multiple wikis from multiple organizations. For
    example:

        [
            {"conn_id": "azure_devops_org_1", "project": "a", "wiki": "a.wiki"},
            {"conn_id": "azure_devops_org_2", "project": "b", "wiki": "b.wiki"},
            {"conn_id": "azure_devops_org_3", "project": "c", "wiki": "c.wiki"}
        ]

    All the pages of all targets/wikis are fetched and saved to the database as
    documents. The saved pages are then flattened into a single list and processed in
    parallel, one mapped task instance per page (using dynamic task mapping), splitting
    it into chunks and generating their embeddings, giving per-page success/failure
    tracking and independent retries.

    Authentication is via Personal Access Token (PAT). If a connection has no PAT, the
    client connects anonymously (suitable only for public projects).
    """

    @task(task_id="set_up_database", retries=RETRIES, retry_delay=RETRY_DELAY)
    def set_up_db():
        """Set up the database."""
        from docflow.db.setup import set_up

        set_up(get_db_url())

    @task(task_id="get_azure_devops_targets", retries=RETRIES, retry_delay=RETRY_DELAY)
    def get_azure_devops_targets() -> list[dict]:
        """Read the list of Azure DevOps targets from the Airflow variable.

        Returns:
            List of target objects, each with a "conn_id", "project" and "wiki".
        """
        targets = Variable.get(
            AZURE_DEVOPS_TARGETS_VAR, default=[], deserialize_json=True
        )

        if not isinstance(targets, list):
            raise ValueError(
                f'"{AZURE_DEVOPS_TARGETS_VAR}" must be a JSON list of targets'
            )

        for t in targets:
            if not all(k in t for k in ("conn_id", "project", "wiki")):
                raise ValueError(
                    'Each Azure DevOps target must have a "conn_id", "project" and '
                    '"wiki"'
                )

        return targets

    @task(task_id="save_documents", retries=RETRIES, retry_delay=RETRY_DELAY)
    def save_documents(target: dict) -> dict:
        """Fetch the pages of an Azure DevOps wiki and save them to the database as
        documents.

        Args:
            target: Target object with a "conn_id", "project" and "wiki".

        Returns:
            Object with the target's "conn_id" and the saved "doc_ids", so that the
            processing step can resolve the same organization's credentials.
        """
        from docflow.azure_devops.ingestion import save_document_batch

        options = _get_azure_devops_options(target["conn_id"])

        doc_ids = save_document_batch(
            get_db_url(),
            project=target["project"],
            wiki=target["wiki"],
            **options,
        )

        return {"conn_id": target["conn_id"], "doc_ids": doc_ids}

    @task(task_id="flatten_documents", retries=RETRIES, retry_delay=RETRY_DELAY)
    def flatten_documents(docs: list[dict]) -> list[dict]:
        """Flatten the per-wiki documents into a flat list of documents.

        Airflow cannot map a task directly over the per-instance output of another
        mapped task, so the saved documents of every wiki are collected here into a
        single flat list — one object per document — so that the processing step can be
        mapped over individual documents.

        Args:
            docs: One object per wiki, each with a "conn_id" and its saved "doc_ids".

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
        """Process an Azure DevOps wiki page document.

        Downloads the document (Azure DevOps wiki page) text, splits it into chunks,
        generates their embeddings, and updates the status of the document. The Azure
        DevOps credentials are resolved from the document's connection so that the
        document (page) text is downloaded from the right organization. This task is
        dynamically mapped over the flattened documents, so each document is processed
        by its own task instance, giving per-document success/failure tracking and
        independent retries.

        Args:
            doc: Object with the document's "conn_id" and its "doc_id".
        """
        from docflow.azure_devops import ingestion

        options = _get_azure_devops_options(doc["conn_id"])
        ingestion.process_document(get_db_url(), doc["doc_id"], pat=options["pat"])

    # Task dependencies
    db_setup = set_up_db()
    targets = get_azure_devops_targets()

    db_setup >> targets  # type: ignore

    docs_by_wiki = save_documents.expand(target=targets)  # type: ignore
    docs = flatten_documents(docs_by_wiki)  # type: ignore
    process_document.expand(doc=docs)  # type: ignore


dag = ingest_azure_devops_wikis()
