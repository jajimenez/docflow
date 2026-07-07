"""PDF ingestion module."""

from uuid import UUID
from pathlib import Path
import logging

from docflow.db import get_session
from docflow.db.models import Document, DocumentSourceType, DocumentStatus

from docflow.documents import (
    DOC_NOT_FOUND,
    get_document,
    save_document,
    process_document,
)


# Messages
PENDING_PDF_FILES_FOUND = "{} pending PDF files found"
NO_FILE_PATH = "Document {} does not have a file path"
ERROR_PROCESSING_DOC = "Error processing document {}: {}"
PDF_FILE_MOVED = "PDF file moved from {} to {}"
ERROR_MOVING_PDF_FILE = "Error moving file {} to {}: {}"

PDF_FILE_NOT_MOVED = (
    "PDF file not moved: Pending and Processed paths could not be determined."
)

BATCH_PROCESSING_FAILED = "{} of {} document(s) failed to process: {}"

# Logger
logger = logging.getLogger(__name__)


def get_incoming_pdf_file_paths(pending_dir: str) -> list[str]:
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
    """Save a batch of PDF documents to the database given their file paths.

    Args:
        db_url: Database URL (e.g.
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


def process_document_batch(
    db_url: str,
    doc_ids: list[str],
    processed_dir: str,
    failed_dir: str,
):
    """Process a batch of existing PDF documents.

    Args:
        db_url: Database URL (e.g.
            "postgresql+psycopg://user:password@localhost:5432/db").
        doc_ids: IDs of the PDF documents to process.
        processed_dir: Absolute path of the Processed directory.
        failed_dir: Absolute path of the Failed directory.
    """
    failed_ids: list[str] = []

    with get_session(db_url) as session:
        for i in doc_ids:
            # Absolute path of the pending PDF file to process
            pending_path: Path | None = None

            # Name of the pending PDF file to process
            pending_name: str | None = None

            # Absolute path where the processed file will be moved (either in the
            # Processed or Failed directory, depending on the result of the processing).
            destination_path: Path | None = None

            try:
                id = UUID(i)  # type: ignore
                doc = get_document(session, id=id)

                if doc is None:
                    raise ValueError(DOC_NOT_FOUND)

                if not doc.source_file_path:
                    raise ValueError(NO_FILE_PATH.format(doc.id))

                pending_path = Path(doc.source_file_path)
                pending_name = pending_path.name

                # Process the document
                process_document(session, id)

                # Set the destination path to the Processed directory
                destination_path = Path(processed_dir) / pending_name
            except Exception as e:
                # Log the error for this specific document
                logger.error(ERROR_PROCESSING_DOC.format(i, e))
                failed_ids.append(i)

                # Set the destination path to the Failed directory
                if pending_name is not None:
                    destination_path = Path(failed_dir) / pending_name
            finally:
                if pending_path is not None and destination_path is not None:
                    try:
                        # Create the destination directory if it doesn't exist
                        destination_path.parent.mkdir(parents=True, exist_ok=True)

                        # Move the pending file to the destination directory
                        pending_path.rename(destination_path)
                    except Exception as e:
                        logger.error(
                            ERROR_MOVING_PDF_FILE.format(
                                pending_path, destination_path, e
                            )
                        )
                    else:
                        # The file was moved successfully
                        logger.info(
                            PDF_FILE_MOVED.format(pending_path, destination_path)
                        )
                else:
                    # The file couldn't be moved because we couldn't determine the
                    # pending and destination paths (the error occurred before the
                    # document was retrieved from the database).
                    logger.warning(PDF_FILE_NOT_MOVED)

    if failed_ids:
        raise RuntimeError(
            BATCH_PROCESSING_FAILED
            .format(len(failed_ids), len(doc_ids), ", ".join(failed_ids))
        )
