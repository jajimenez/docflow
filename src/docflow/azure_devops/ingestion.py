"""Azure DevOps Wiki ingestion module.

This module orchestrates the ingestion: it lists the pages of an Azure DevOps wiki,
saves them as documents and processes them (text extraction, chunking and embedding
generation).

Authentication is optional. When no PAT (Personal Access Token) is provided, the client
connects anonymously, which is only suitable for public projects.
"""

from uuid import UUID
import logging

from docflow.db import get_session
from docflow.db.models import Document, DocumentSourceType, DocumentStatus

from docflow.azure_devops.extraction import (
    get_wiki_pages,
    get_page_url,
    get_page_title,
    extract_text,
)

from docflow.documents import (
    DOC_NOT_FOUND,
    get_document,
    save_document,
    process_document as process_document_pipeline,
)


# Messages
NO_SOURCE_URL = "Document {} does not have a source URL"
ERROR_PROCESSING_DOC = "Error processing document {}: {}"

# Logger
logger = logging.getLogger(__name__)


def save_document_batch(
    db_url: str,
    org_url: str,
    project: str,
    wiki: str,
    pat: str | None = None,
) -> list[str]:
    """Fetch the pages of an Azure DevOps wiki and save them as documents.

    For each page, a document is created (or updated if it already exists, identified by
    its source URL). Only the page title and its URL are stored; the page content is
    downloaded later, when the document is processed.

    Args:
        db_url: Knowledge Database URL (e.g.
            ``"postgresql+psycopg://user:password@localhost:5432/db"``).
        org_url: Base URL of the Azure DevOps organization, e.g.
            ``"https://dev.azure.com/org"``.
        project: Project name or ID (e.g. ``"Project"``).
        wiki: Wiki name or ID (e.g. ``"Project.wiki"``).
        pat: Personal Access Token for authentication (optional).

    Returns:
        Document IDs.
    """
    pages = get_wiki_pages(org_url, project, wiki, pat)
    doc_ids: list[str] = []

    with get_session(db_url) as session:
        for page in pages:
            page_url = get_page_url(page)

            # Get the document from the database if it exists (identified by its URL)
            doc = get_document(session, source_url=page_url)

            if doc:
                # Update the existing document and reset its status to Pending
                doc.title = get_page_title(page)
                doc.status = DocumentStatus.pending
            else:
                # Create a new document
                doc = Document(
                    source_type=DocumentSourceType.azure_devops,
                    title=get_page_title(page),
                    source_url=page_url,
                    status=DocumentStatus.pending,
                )  # type: ignore

            # Save (create/update) the document
            id = str(save_document(session, doc))
            doc_ids.append(id)

    return doc_ids


def process_document(db_url: str, doc_id: str, pat: str | None = None):
    """Process an Azure DevOps wiki document.

    Downloads the document's page from Azure DevOps, splits it into chunks and generates
    their embeddings. The organization URL, project name, wiki identifier and page ID
    are all derived from the document's source URL, so only the PAT is required as an
    extra argument.

    Args:
        db_url: Knowledge Database URL (e.g.
            ``"postgresql+psycopg://user:password@localhost:5432/db"``).
        doc_id: ID of the Azure DevOps wiki document to process.
        pat: Personal Access Token for authentication (optional).

    Raises:
        Exception: If the document could not be processed. The exception is re-raised so
            that the caller (e.g. an Airflow task) can mark the attempt as failed.
    """

    with get_session(db_url) as session:
        try:
            id = UUID(doc_id)
            doc = get_document(session, id=id)

            if not doc:
                raise ValueError(DOC_NOT_FOUND)

            if not doc.source_url:
                raise ValueError(NO_SOURCE_URL.format(doc.id))

            process_document_pipeline(
                session,
                id,
                lambda d: extract_text(d.source_url, pat),  # type: ignore
            )
        except Exception as e:
            # Log the error and re-raise so the caller can mark this attempt as failed
            logger.error(ERROR_PROCESSING_DOC.format(doc_id, e))
            raise
