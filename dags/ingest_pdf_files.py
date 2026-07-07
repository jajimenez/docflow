"""PDF files ingestion DAG."""

from datetime import datetime, timedelta

from airflow.sdk import dag, task, Variable, PokeReturnValue


# We place all posible imports in the task functions to keep the DAG parsing fast

RETRIES = 3
RETRY_DELAY = timedelta(minutes=5)


@dag(
    dag_id="ingest_pdf_files",
    start_date=datetime(2026, 1, 1),
    schedule="@continuous",  # Run continuously, checking for new documents
    max_active_runs=1,
    catchup=False,
    tags=["docflow", "PDF"],
)
def ingest_pdf_files():
    """DAG to ingest PDF files from the file system and process them.

    This DAG continuously checks for PDF files in the Pending directory of the file
    system. When new PDF files are found, it saves them to the database and processes
    them. The processing includes extracting text, splitting it into chunks, generating
    embeddings, and moving the PDF files to the appropriate directories based on the
    processing outcome (Processed or Failed).
    """

    @task(task_id="set_up_database", retries=RETRIES, retry_delay=RETRY_DELAY)
    def set_up_db():
        """Set up the database."""
        from airflow.sdk import Connection
        from docflow.db.setup import set_up

        conn = Connection.get("knowledge_db")

        db_url = (
            f"postgresql+psycopg://{conn.login}:{conn.password}@{conn.host}:{conn.port}"
            f"/{conn.schema}"
        )

        set_up(db_url)

    @task.sensor(
        task_id="wait_for_pdf_files",
        mode="reschedule",
        poke_interval=30,
        timeout=3600,
        retries=RETRIES,
        retry_delay=RETRY_DELAY,
    )
    def wait_for_pdf_files() -> PokeReturnValue:
        """Wait until PDF files appear in the Pending directory.

        Returns:
            PokeReturnValue with the absolute file paths when files are found.
        """
        from docflow.ingestion.pdf import get_incoming_pdf_file_paths

        pending_dir = Variable.get("DOCFLOW_PDF_PENDING_DIR")
        paths = get_incoming_pdf_file_paths(pending_dir)

        return PokeReturnValue(is_done=len(paths) > 0, xcom_value=paths)

    @task(
        task_id="save_documents",
        retries=RETRIES,
        retry_delay=RETRY_DELAY,
    )
    def save_documents(pdf_file_paths: list[str]) -> list[str]:
        """Save the PDF documents to the database.

        Args:
            pdf_file_paths: Absolute paths of the PDF files.

        Returns:
            Document IDs.
        """
        from airflow.sdk import Connection
        from docflow.ingestion.pdf import save_document_batch

        conn = Connection.get("knowledge_db")

        db_url = (
            f"postgresql+psycopg://{conn.login}:{conn.password}"
            f"@{conn.host}:{conn.port}/{conn.schema}"
        )

        return save_document_batch(db_url, pdf_file_paths)

    @task(
        task_id="process_documents",
        retries=RETRIES,
        retry_delay=RETRY_DELAY,
    )
    def process_documents(doc_ids: list[str]):
        """Process the PDF documents.

        Extracts text, generates embeddings, and moves each PDF file to the Processed or
        Failed directory depending on the outcome.

        Args:
            doc_ids: Document IDs.
        """
        from airflow.sdk import Connection
        from docflow.ingestion.pdf import process_document_batch

        conn = Connection.get("knowledge_db")

        db_url = (
            f"postgresql+psycopg://{conn.login}:{conn.password}"
            f"@{conn.host}:{conn.port}/{conn.schema}"
        )

        processed_dir = Variable.get("DOCFLOW_PDF_PROCESSED_DIR")
        failed_dir = Variable.get("DOCFLOW_PDF_FAILED_DIR")

        process_document_batch(db_url, doc_ids, processed_dir, failed_dir)

    # Task dependencies
    db_setup = set_up_db()
    doc_paths = wait_for_pdf_files()
    doc_ids = save_documents(doc_paths)  # type: ignore
    doc_proc = process_documents(doc_ids)  # type: ignore

    db_setup >> doc_paths >> doc_ids >> doc_proc  # type: ignore


dag = ingest_pdf_files()
