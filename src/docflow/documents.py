"""Module for managing documents."""

import logging
from uuid import UUID
from pathlib import Path

from sqlmodel import Session, select

from docflow.db.models import Document, DocumentStatus, DocumentChunk
from docflow.pdf import extract_text as extract_pdf_text
from docflow.text import split_text
from docflow.text import get_embedding
from docflow.config import settings


# Messages
DOC_CREATED = "Document {} created"
DOC_UPDATED = "Document {} updated"
DOC_NOT_FOUND = "Document {} not found"
PROCCESSING_DOC = "Processing document {}..."
EXTRACTING_TEXT = "Extracting text from document {}..."
SPLITTING_TEXT = "Splitting text of document {} into chunks..."
GEN_EMBEDDINGS = "Generating embeddings of text chunks of document {}..."
PROC_DOC_COMPLETED = "Processing of document {} completed"
PROC_DOC_FAILED = "Processing of document {} failed"

# Logger
logger = logging.getLogger(__name__)


def get_document(
    session: Session,
    id: UUID | None = None,
    source_file_path: str | None = None,
) -> Document | None:
    """Get a document by its ID or its file path (if it's a PDF file).

    Args:
        session: Database session.
        id: Document ID (optional).
        source_file_path: Document source file path (optional).

    Returns:
        Document if found or None otherwise.
    """
    stmt = select(Document)

    if id is not None:
        stmt = stmt.where(Document.id == id)
    elif source_file_path is not None:
        stmt = stmt.where(Document.source_file_path == source_file_path)
    else:
        raise ValueError('Either "id" or "source_file_path" must be provided.')

    return session.exec(stmt).first()


def save_document(session: Session, doc: Document) -> UUID:
    """Save a document to the database.

    If the document is new (its ID is None), a new row is inserted in the Documents
    table and the ID of the row is generated automatically by the database server. If
    the document already exists (its ID is not None), a row must exist in the Documents
    table with the same ID (otherwise, a `ValueError` is raised), and the row is
    updated. In either case, the Updated At field is updated to the current date-time
    automatically by the database server.

    Args:
        session: Database session.
        doc: Document to save.

    Returns:
        Document ID.
    """
    is_new = doc.id is None

    # If it's an update, verify that the document exists
    if not is_new:
        existing_doc = session.get(Document, doc.id)

        if existing_doc is None:
            message = DOC_NOT_FOUND.format(doc.id)
            logger.error(message)

            raise ValueError(message)

    # "merge" handles both insertion (when the ID is None) and update (when the ID
    # exists).
    doc = session.merge(doc)
    session.commit()

    if is_new:
        logger.info(DOC_CREATED.format(doc.id))
    else:
        logger.info(DOC_UPDATED.format(doc.id))

    # Refresh the document to get the updated fields ("id" or "updated_at") from the
    # database.
    session.refresh(doc)

    # Return the document ID
    return doc.id  # type: ignore


# TO-DO
def extract_text(doc: Document) -> str:
    """Extract the text of a document.

    Args:
        doc: Document to extract the text from.

    Returns:
        Document text in Markdown format.
    """
    if doc.source_type == "pdf":
        if not doc.source_file_path:
            message = f'Document "{doc.id}" does not have a file path'
            logger.error(message)

            raise ValueError(message)

        if not Path(doc.source_file_path).exists():
            message = f'File path "{doc.source_file_path}" does not exist'
            logger.error(message)

            raise ValueError(message)

        return extract_pdf_text(settings.pdf_extraction_models_path, doc.source_file_path)
    elif doc.source_type == "github":
        raise NotImplementedError("Text extraction from GitHub is not implemented yet")
    elif doc.source_type == "azure_devops":
        raise NotImplementedError(
            "Text extraction from Azure DevOps is not implemented yet"
        )
    elif doc.source_type == "confluence":
        raise NotImplementedError(
            "Text extraction from Confluence is not implemented yet"
        )
    else:
        message = f'Unknown source type "{doc.source_type}" for document "{doc.id}"'
        logger.error(message)

        raise ValueError(message)


def process_document(session: Session, doc_id: UUID):
    """Process an existing document.

    When this function starts, the status of the document is set to Processing. When
    this function ends, the status is set to Processed. If an exception occurs during
    the processing, the status is set to Failed.

    Args:
        session: Database session.
        doc_id: ID of the document to process.
    """
    # Get the document from the database
    doc = session.get(Document, doc_id)

    # Check that the document exists
    if doc is None:
        message = DOC_NOT_FOUND.format(doc_id)
        logger.error(message)

        raise ValueError(message)

    try:
        # Set the status to Processing
        doc.status = DocumentStatus.processing
        session.commit()
        logger.info(PROCCESSING_DOC.format(doc.id))

        # Delete existing chunks (via a copy with "list" to avoid modifying the
        # collection while iterating over it).
        for c in list(doc.chunks):
            session.delete(c)

        session.commit()

        # Extract text from the file
        logger.info(EXTRACTING_TEXT.format(doc.id))
        text = extract_text(doc)

        # Split the text into chunks
        logger.info(SPLITTING_TEXT.format(doc.id))
        chunks = split_text(text, settings.chunk_size, settings.chunk_overlap)

        # For each chunk, get its embedding and save the chunk to the database
        logger.info(GEN_EMBEDDINGS.format(doc.id))

        for i, c in enumerate(chunks):
            embedding = get_embedding(
                settings.embeddings_api_url,
                settings.embeddings_api_timeout,
                settings.embeddings_model,
                c,
            )

            dc = DocumentChunk(
                document_id=doc.id,
                chunk_index=i,
                chunk_text=c,
                embedding=embedding,
            )  # type: ignore

            session.add(dc)

        # Set the status to Processed
        doc.status = DocumentStatus.processed
        session.commit()
        logger.info(PROC_DOC_COMPLETED.format(doc.id))

    except Exception as e:
        # Rollback the current transaction
        session.rollback()

        try:
            # Set the status to Failed
            doc.status = DocumentStatus.failed
            session.commit()
        except Exception:
            session.rollback()

        logger.error(PROC_DOC_FAILED.format(doc.id))
        logger.exception(e)

        # Re-raise the exception
        raise e
