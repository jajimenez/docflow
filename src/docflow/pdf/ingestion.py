"""PDF ingestion module.

This module orchestrates the ingestion: it lists the incoming PDF files, saves them as
documents and processes them.
"""

from uuid import UUID
from pathlib import Path
import logging

from docflow.db import get_session
from docflow.db.models import Document, DocumentSourceType, DocumentStatus
from docflow.pdf.extraction import extract_text

from docflow.documents import (
    DOC_NOT_FOUND,
    get_document,
    save_document,
    process_document as process_document_pipeline,
)

from docflow.config import settings


# Messages
PENDING_PDF_FILES_FOUND = "{} pending PDF file(s) found"
NO_FILE_PATH = "Document {} does not have a file path"
FILE_NOT_FOUND = 'File path "{}" does not exist'
ERROR_PROCESSING_DOC = "Error processing document {}: {}"
FILE_MOVED = "File moved from {} to {}"
ERROR_MOVING_FILE = "Error moving file {} to {}: {}"

# Logger
logger = logging.getLogger(__name__)


def get_pending_pdf_file_paths(pending_dir: str) -> list[str]:
    """Get the absolute paths of the PDF files in the Pending directory.

    Args:
        pending_dir: Absolute path of the Pending directory.

    Returns:
        Absolute paths of the PDF files.
    """
    # Get all the paths of PDF files in the Pending directory
    paths = list(Path(pending_dir).glob("*.pdf"))
    logger.info(PENDING_PDF_FILES_FOUND.format(len(paths)))

    return [str(p) for p in paths]


def save_document_batch(db_url: str, pdf_file_paths: list[str]) -> list[str]:
    """Save a batch of PDF documents to the Knowledge Database given their file paths.

    Args:
        db_url: Knowledge Database URL (e.g.
            "postgresql+psycopg://user:password@localhost:5432/db").
        pdf_file_paths: Absolute paths of the PDF files.

    Returns:
        Document IDs.
    """
    doc_ids = []

    with get_session(db_url) as session:
        for path in pdf_file_paths:
            # Get document from the database if it exists
            doc = get_document(session, source_file_path=path)

            if doc:
                # Reset the document status to Pending
                doc.status = DocumentStatus.pending
            else:
                # Extract the file name without the extension from the path and use it
                # as the document title.
                title = Path(path).stem

                # Create a Document instance
                doc = Document(
                    source_type=DocumentSourceType.pdf,
                    title=title,
                    source_file_path=path,
                    status=DocumentStatus.pending,
                )  # type: ignore

            # Save (create/update) the document
            id = str(save_document(session, doc))
            doc_ids.append(id)

    return doc_ids


def _move_file(src: Path, dest: Path) -> None:
    """Move a file.

    Args:
        src: Absolute path of the source file.
        dest: Absolute path of the destination file.
    """
    try:
        # Create the destination directory if it doesn't exist
        dest.parent.mkdir(parents=True, exist_ok=True)

        # Move the source file to the destination directory
        src.rename(dest)
    except Exception as e:
        logger.error(ERROR_MOVING_FILE.format(src, dest, e))
    else:
        logger.info(FILE_MOVED.format(src, dest))


def process_document(
    db_url: str,
    doc_id: str,
    processed_dir: str,
    failed_dir: str,
    last_attempt: bool = True,
):
    """Process a PDF document.

    It extracts the text of the PDF file, splits it into chunks and generates their
    embeddings, then moves the PDF file out of the Pending directory: to the Processed
    directory on success, or to the Failed directory on failure. The file is only moved
    to the Failed directory on the last attempt, so that intermediate retries can still
    find it in the Pending directory.

    Args:
        db_url: Knowledge Database URL (e.g.
            "postgresql+psycopg://user:password@localhost:5432/db").
        doc_id: ID of the PDF document to process.
        processed_dir: Absolute path of the Processed directory.
        failed_dir: Absolute path of the Failed directory.
        last_attempt: Whether this is the last processing attempt. When True, a failed
            file is moved to the Failed directory; otherwise it is left in the Pending
            directory so that a retry can find it.

    Raises:
        Exception: If the document could not be processed. The exception is re-raised so
            that the caller (e.g. an Airflow task) can mark the attempt as failed.
    """
    # Absolute path of the pending PDF file to process
    pending_path: Path | None = None

    # Absolute path where the file will be moved (either in the Processed or Failed
    # directory, depending on the result of the processing).
    destination_path: Path | None = None

    with get_session(db_url) as session:
        try:
            id = UUID(doc_id)
            doc = get_document(session, id=id)

            if not doc:
                raise ValueError(DOC_NOT_FOUND)

            if not doc.source_file_path:
                raise ValueError(NO_FILE_PATH.format(doc.id))

            pending_path = Path(doc.source_file_path)

            if not pending_path.exists():
                raise ValueError(FILE_NOT_FOUND.format(pending_path))

            # Process the document
            process_document_pipeline(
                session,
                id,
                lambda d: extract_text(
                    settings.pdf_extraction_models_path,
                    d.source_file_path,  # type: ignore
                )
            )

            # The document was processed successfully: move it to the Processed
            # directory.
            destination_path = Path(processed_dir) / pending_path.name
        except Exception as e:
            # Log the error for this specific document
            logger.error(ERROR_PROCESSING_DOC.format(doc_id, e))

            # Only move the file to the Failed directory on the last attempt, so that
            # intermediate retries can still find it in the Pending directory.
            if last_attempt and pending_path is not None:
                destination_path = Path(failed_dir) / pending_path.name

            # Re-raise so the caller can mark this attempt as failed (and retry it).
            raise
        finally:
            if pending_path is not None and destination_path is not None:
                _move_file(pending_path, destination_path)
