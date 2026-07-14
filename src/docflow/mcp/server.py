"""Docflow MCP server.

Exposes three tools that allow AI agents to query the Knowledge Database:

- search_documents:    semantic similarity search over all document chunks.
- list_documents:      list all successfully ingested documents.
- get_document_chunks: retrieve the full ordered text of a specific document.
"""

import hmac
import logging
from uuid import UUID

import uvicorn
from mcp.server.fastmcp import FastMCP
from sqlmodel import select
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from docflow.config import settings
from docflow.db import get_session
from docflow.db.models import (
    Document,
    DocumentChunk,
    DocumentSourceType,
    DocumentStatus,
)
from docflow.search import get_most_similar_chunks

logger = logging.getLogger(__name__)

mcp = FastMCP("docflow")


class _BearerAuthMiddleware(BaseHTTPMiddleware):
    """Validates ``Authorization: Bearer <token>`` on every incoming request.

    Uses ``hmac.compare_digest`` for the token comparison to prevent
    timing-based side-channel attacks.
    """

    def __init__(self, app: ASGIApp, api_key: str) -> None:
        super().__init__(app)
        self._api_key = api_key

    async def dispatch(self, request: Request, call_next):
        auth = request.headers.get("Authorization", "")
        scheme, _, token = auth.partition(" ")

        if scheme.lower() != "bearer" or not hmac.compare_digest(token, self._api_key):
            logger.warning(
                "Rejected unauthenticated request: %s %s",
                request.method,
                request.url.path,
            )

            return Response("Unauthorized", status_code=401, media_type="text/plain")

        return await call_next(request)


@mcp.tool()
def search_documents(query: str, limit: int = 5) -> list[dict]:
    """Search for document chunks semantically similar to the given query.

    Returns the most relevant text chunks with source attribution (title,
    source type, URL or file path), sorted by relevance (most similar
    first). Use this as the primary tool to answer questions about the
    contents of the knowledge base.

    Each result includes a ``document_id`` that can be passed to
    ``get_document_chunks`` to retrieve the full text of that document.

    Args:
        query: Natural language question or keywords to search for.
        limit: Maximum number of chunks to return. Must be between 1 and 20.
               Defaults to 5.
    """
    if not 1 <= limit <= 20:
        raise ValueError("limit must be between 1 and 20")

    chunks = get_most_similar_chunks(
        db_url=settings.knowledge_db_url,
        api_url=settings.embeddings_api_url,
        api_timeout=settings.embeddings_api_timeout,
        model=settings.embeddings_model,
        text=query,
        limit=limit,
    )

    return [
        {
            "chunk_index": c.chunk_index,
            "text": c.chunk_text,
            "document_id": str(c.document.id),
            "document_title": c.document.title,
            "document_source_type": c.document.source_type.value,
            "document_source_file_path": c.document.source_file_path,
            "document_source_url": c.document.source_url,
        }
        for c in chunks
    ]


@mcp.tool()
def list_documents(source_type: str | None = None) -> list[dict]:
    """List all successfully ingested documents in the knowledge base.

    Returns document metadata ordered by ingestion date (oldest first).
    Use this to discover what sources are available or to obtain a
    ``document_id`` to pass to ``get_document_chunks``.

    Args:
        source_type: Optional filter. One of ``"pdf_file"``,
            ``"azure_devops_wiki_page"``, or ``"confluence_page"``.
    """
    with get_session(settings.knowledge_db_url) as session:
        stmt = (
            select(Document)
            .where(Document.status == DocumentStatus.processed)
            .order_by(Document.created_at)
        )

        if source_type is not None:
            try:
                st = DocumentSourceType(source_type)
            except ValueError:
                valid = ", ".join(v.value for v in DocumentSourceType)
                raise ValueError(
                    f"Invalid source_type '{source_type}'. Valid values: {valid}"
                )
            stmt = stmt.where(Document.source_type == st)

        documents = session.exec(stmt).all()  # type: ignore

    return [
        {
            "id": str(doc.id),
            "title": doc.title,
            "source_type": doc.source_type.value,
            "source_file_path": doc.source_file_path,
            "source_url": doc.source_url,
            "created_at": doc.created_at.isoformat() if doc.created_at else None,
        }
        for doc in documents
    ]


@mcp.tool()
def get_document_chunks(document_id: str) -> list[dict]:
    """Retrieve the full text of a document as an ordered list of chunks.

    Use this to read the complete content of a document identified from
    ``list_documents`` or from the ``document_id`` field in
    ``search_documents`` results. Chunks are returned in reading order
    (``chunk_index`` ascending).

    Args:
        document_id: UUID of the document (obtained from
            ``list_documents`` or ``search_documents``).
    """
    try:
        doc_uuid = UUID(document_id)
    except ValueError:
        raise ValueError(f"'{document_id}' is not a valid document UUID")

    with get_session(settings.knowledge_db_url) as session:
        stmt = (
            select(DocumentChunk)
            .where(DocumentChunk.document_id == doc_uuid)  # type: ignore
            .order_by(DocumentChunk.chunk_index)
        )
        chunks = session.exec(stmt).all()  # type: ignore

    if not chunks:
        raise ValueError(f"No document found with ID '{document_id}'")

    return [
        {"chunk_index": c.chunk_index, "text": c.chunk_text}
        for c in chunks
    ]


def main() -> None:
    """Start the MCP HTTP server."""
    api_key = settings.mcp_api_key.get_secret_value() if settings.mcp_api_key else None

    if not api_key:
        raise ValueError(
            "DOCFLOW_MCP_API_KEY environment variable must not be empty"
        )

    app = mcp.streamable_http_app()
    app.add_middleware(_BearerAuthMiddleware, api_key=api_key)
    uvicorn.run(app, host="0.0.0.0", port=settings.mcp_port)
