"""Confluence ingestion module.

This module only orchestrates the ingestion: it lists the pages of a space, saves them
as documents and processes them.

This module contains the logic to ingest the pages of a Confluence space into the
knowledge database. It mirrors the PDF ingestion module: it fetches the pages of a
space, saves them as documents and processes them (text extraction, chunking and
embedding generation).

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

from docflow.confluence.extraction import (
    get_space_pages,
    get_page_url,
    extract_text as extract_confluence_text,
)

from docflow.documents import (
    get_document,
    save_document,
    process_document,
)


# Messages
NO_SOURCE_URL = "Document {} does not have a source URL"
ERROR_PROCESSING_DOC = "Error processing document {}: {}"
BATCH_PROCESSING_FAILED = "{} of {} document(s) failed to process: {}"

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
                    source_type=DocumentSourceType.confluence,
                    title=page.get("title", page_url),
                    source_url=page_url,
                    status=DocumentStatus.pending,
                )  # type: ignore

            # Save (create/update) the document
            id = str(save_document(session, doc))
            doc_ids.append(id)

    return doc_ids


def process_document_batch(
    db_url: str,
    doc_ids: list[str],
    base_url: str,
    username: str | None = None,
    password: str | None = None,
    token: str | None = None,
    verify_ssl: bool = True,
    cloud: bool = False,
):
    """Process a batch of existing Confluence documents.

    For each document, its page is downloaded from Confluence and converted to Markdown,
    split into chunks and embedded. The Confluence credentials are passed in so that each
    batch is processed against the right host, which allows ingesting multiple Confluence
    instances. If one or more documents fail to process, the others are still processed
    and a ``RuntimeError`` is raised at the end.

    Args:
        db_url: Knowledge Database URL (e.g.
            "postgresql+psycopg://user:password@localhost:5432/db").
        doc_ids: IDs of the Confluence documents to process.
        base_url: Base URL of the Confluence instance (e.g.
            "https://confluence.example.com").
        username: User name for basic authentication (optional).
        password: Password or API token for basic authentication (optional).
        token: Personal access token for token-based authentication (optional).
        verify_ssl: Whether to verify the TLS certificate of the server.
        cloud: Whether the instance is Confluence Cloud (True) or Server/Data Center
            (False).
    """

    def extract(doc: Document) -> str:
        if not doc.source_url:
            raise ValueError(NO_SOURCE_URL.format(doc.id))

        return extract_confluence_text(
            doc.source_url,  # Page URL
            base_url,
            username,
            password,
            token,
            verify_ssl,
            cloud,
        )

    failed_ids: list[str] = []

    with get_session(db_url) as session:
        for i in doc_ids:
            try:
                id = UUID(i)
                process_document(session, id, extract)
            except Exception as e:
                # Log the error for this specific document and continue with the rest
                logger.error(ERROR_PROCESSING_DOC.format(i, e))
                failed_ids.append(i)

    if failed_ids:
        raise RuntimeError(
            BATCH_PROCESSING_FAILED.format(
                len(failed_ids), len(doc_ids), ", ".join(failed_ids)
            )
        )
