"""Confluence ingestion module.

This module contains the logic to ingest the pages of one or more Confluence spaces
into the knowledge database: it fetches the pages of a space, saves them as documents
and processes them (text extraction, chunking and embedding generation).

The functions in this module are intentionally Airflow-agnostic: they receive plain
values (database URL, Confluence URL, credentials, etc.) so that the credentials and
options can be resolved by the DAG from Airflow connections, secrets or variables and
passed in.

Authentication is optional. When no credentials are provided, the Confluence client
connects anonymously, which is useful when Confluence is readable from within the
company network without logging in.
"""

from uuid import UUID
import logging

from docflow.db import get_session
from docflow.db.models import Document, DocumentSourceType, DocumentStatus
from docflow.confluence.auth import get_client
from docflow.confluence.extraction import get_space_pages, get_page_url, extract_text

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
    base_url: str,
    space_key: str,
    username: str | None = None,
    password: str | None = None,
    token: str | None = None,
    verify_ssl: bool = True,
    cloud: bool = False,
) -> list[str]:
    """Fetch the pages of a Confluence space and save them as documents.

    For each page, a document is created (or updated if it already exists, identified by
    its source URL). Only the page title and its URL are stored; the page body is
    downloaded later, when the document is processed (see
    ``docflow.confluence.extraction``).

    Args:
        db_url: Knowledge Database URL (e.g.
            "postgresql+psycopg://user:password@localhost:5432/db").
        base_url: Base URL of the Confluence instance (e.g.
            "https://confluence.example.com").
        space_key: Key of the Confluence space (e.g. "ENG").
        username: User name for basic authentication (optional).
        password: Password or API token for basic authentication (optional).
        token: Personal access token for token-based authentication (optional).
        verify_ssl: Whether to verify the TLS certificate of the server.
        cloud: Whether the instance is Confluence Cloud (True) or Server/Data Center
            (False).

    Returns:
        Document IDs.
    """
    client = get_client(base_url, username, password, token, verify_ssl, cloud)
    pages = get_space_pages(client, space_key)
    doc_ids: list[str] = []

    with get_session(db_url) as session:
        for page in pages:
            page_url = get_page_url(page, base_url)

            # Get the document from the database if it exists (identified by its URL)
            doc = get_document(session, source_url=page_url)

            if doc:
                # Update the existing document and reset its status to Pending
                doc.title = page.get("title", doc.title)
                doc.status = DocumentStatus.pending
            else:
                # Create a new document
                doc = Document(
                    source_type=DocumentSourceType.confluence_page,
                    title=page.get("title", page_url),
                    source_url=page_url,
                    status=DocumentStatus.pending,
                )  # type: ignore

            # Save (create/update) the document
            id = str(save_document(session, doc))
            doc_ids.append(id)

    return doc_ids


def process_document(
    db_url: str,
    doc_id: str,
    base_url: str,
    username: str | None = None,
    password: str | None = None,
    token: str | None = None,
    verify_ssl: bool = True,
    cloud: bool = False,
):
    """Process a Confluence document.

    Downloads the document's page from Confluence, converts it to Markdown, splits it
    into chunks and generates their embeddings. The Confluence credentials are passed in
    so that the page is downloaded from the right host, which allows ingesting multiple
    Confluence instances.

    Args:
        db_url: Knowledge Database URL (e.g.
            "postgresql+psycopg://user:password@localhost:5432/db").
        doc_id: ID of the Confluence document to process.
        base_url: Base URL of the Confluence instance (e.g.
            "https://confluence.example.com").
        username: User name for basic authentication (optional).
        password: Password or API token for basic authentication (optional).
        token: Personal access token for token-based authentication (optional).
        verify_ssl: Whether to verify the TLS certificate of the server.
        cloud: Whether the instance is Confluence Cloud (True) or Server/Data Center
            (False).

    Raises:
        Exception: If the document could not be processed. The exception is re-raised so
            that the caller (e.g. an Airflow task) can mark the attempt as failed.
    """
    with get_session(db_url) as session:
        try:
            id = UUID(doc_id)
            doc = get_document(session, id=id)

            if not doc:
                raise ValueError(DOC_NOT_FOUND.format(doc_id))

            if not doc.source_url:
                raise ValueError(NO_SOURCE_URL.format(doc.id))

            process_document_pipeline(
                session,
                id,
                lambda d: extract_text(
                    d.source_url,  # type: ignore
                    base_url,
                    username,
                    password,
                    token,
                    verify_ssl,
                    cloud,
                )
            )
        except Exception as e:
            # Log the error and re-raise so the caller can mark this attempt as failed
            logger.error(ERROR_PROCESSING_DOC.format(doc_id, e))
            raise
