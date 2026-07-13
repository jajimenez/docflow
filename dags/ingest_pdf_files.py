"""PDF files ingestion DAG."""

from datetime import datetime, timedelta

from airflow.sdk import dag, task, Variable, PokeReturnValue

from common import get_db_url, MAX_ACTIVE_PROCESSING_TASKS


# We place all possible imports in the task functions to keep the DAG parsing fast

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
    """DAG to ingest PDF files from the file system.

    This DAG continuously checks for PDF files in the Pending directory of the file
    system. When new PDF files are found, it saves them to the database and processes
    them. The processing includes extracting text, splitting it into chunks, generating
    embeddings, and moving the PDF files to the appropriate directories based on the
    processing outcome (Processed or Failed).
    """

    @task(task_id="set_up_database", retries=RETRIES, retry_delay=RETRY_DELAY)
    def set_up_db():
        """Set up the database."""
        from docflow.db.setup import set_up

        set_up(get_db_url())

    @task.sensor(
        task_id="wait_for_pdf_files",
        mode="reschedule",
        poke_interval=30,
        timeout=3600,

        # On timeout (no PDF files found within the time window), mark the task as
        # Skipped instead of Failed. The Continuous schedule then immediately starts a
        # new run, so this avoids noisy failures while idly polling for files.
        soft_fail=True,

        retries=RETRIES,
        retry_delay=RETRY_DELAY,
    )
    def wait_for_pdf_files() -> PokeReturnValue:
        """Wait until PDF files appear in the Pending directory.

        Returns:
            PokeReturnValue with the absolute file paths when files are found.
        """
        from docflow.pdf.ingestion import get_pending_pdf_file_paths

        pending_dir = Variable.get("docflow_pdf_pending_dir")
        paths = get_pending_pdf_file_paths(pending_dir)

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
        from docflow.pdf.ingestion import save_document_batch

        return save_document_batch(get_db_url(), pdf_file_paths)

    @task(
        task_id="process_document",
        retries=RETRIES,
        retry_delay=RETRY_DELAY,
        max_active_tis_per_dagrun=MAX_ACTIVE_PROCESSING_TASKS,
    )
    def process_document(doc_id: str):
        """Process a PDF document.

        Extracts text, generates embeddings, and moves the PDF file to the Processed or
        Failed directory depending on the outcome. This task is dynamically mapped over
        the saved documents, so each PDF file is processed by its own task instance,
        giving per-file success/failure tracking and independent retries.

        Args:
            doc_id: Document ID.
        """
        from airflow.sdk import get_current_context
        from docflow.pdf import ingestion

        processed_dir = Variable.get("docflow_pdf_processed_dir")
        failed_dir = Variable.get("docflow_pdf_failed_dir")

        # Only move the file to the Failed directory once all tries have been made, so
        # that intermediate tries can still find it in the Pending directory.
        ti = get_current_context()["ti"]  # type: ignore
        is_last_attempt = ti.try_number > ti.max_tries

        ingestion.process_document(
            get_db_url(),
            doc_id,
            processed_dir,
            failed_dir,
            is_last_attempt=is_last_attempt,
        )

    # Task dependencies
    db_setup = set_up_db()
    doc_paths = wait_for_pdf_files()
    doc_ids = save_documents(doc_paths)  # type: ignore
    process_document.expand(doc_id=doc_ids)

    db_setup >> doc_paths  # type: ignore


dag = ingest_pdf_files()
