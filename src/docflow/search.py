"""Search module."""

from sqlalchemy import text as _text
from sqlalchemy.orm import selectinload
from sqlmodel import select

from docflow.db import get_session
from docflow.db.models import DocumentChunk
from docflow.text import get_embedding


def get_most_similar_chunks(
    db_url: str,
    api_url: str,
    api_timeout: int,
    model: str,
    text: str,
    limit: int = 5,
) -> list[DocumentChunk]:
    """Get the most similar document chunks to a text.

    Args:
        db_url: Knowledge Database URL (e.g.
            "postgresql+psycopg://user:password@localhost:5432/db").
        api_url: Ollama embedding API URL (e.g.
            "http://localhost:11434/api/embeddings").
        api_timeout: API requests timeout in seconds.
        model: Embedding model to use.
        text: Text to search for.
        limit: Maximum number of chunks to return.
    """
    # Validate limit
    if not isinstance(limit, int) or limit < 1 or limit > 1000:
        raise ValueError(
            f"Invalid limit: {limit}. Must be an integer between 1 and 1000."
        )

    # Get the text embedding
    embedding = get_embedding(api_url, api_timeout, model, text)

    # Validate embedding
    if not isinstance(embedding, list) or not embedding:
        raise ValueError("Invalid embedding: must be a non-empty list")

    if not all(isinstance(x, (int, float)) for x in embedding):
        raise ValueError("Invalid embedding: all elements must be numeric")

    # Search for the most similar document chunks in the database
    with get_session(db_url) as session:
        # We search for the documents. The SQL statement is a raw because SQLModel does
        # not support the "<=>" operator used by the PgVector extension for similarity
        # search.
        #
        # The "<=>" operator calculates the distance between two vectors, which is a
        # number between 0 (the vectors are identical) and 2 (the vectors point in
        # opposite directions). A value of 1 means that the vectors are perpendicular.
        # Therefore, the smaller the distance, the more similar the vectors are.
        #
        # We format the statement string with the "embedding" variable between single
        # quotes, which is the format of the "embedding" vector column in SQL
        # statements. We can't use the "params" argument of the "text" function because
        # it doesn't translate the "embedding" variable to the proper format. However,
        # this is safe because we have already validated the "embedding" variable.
        #
        # We also format the "limit" value directly in the string for consistency, but
        # we have validated it before.
        search_sql = _text(
            "SELECT dc.id "
            "FROM document_chunks dc "
            f"ORDER BY dc.embedding <=> '{embedding}' "
            f"LIMIT {limit};"
        )

        rows = session.exec(search_sql)  # type: ignore
        chunk_ids = [r[0] for r in rows]

        if not chunk_ids:
            return []

        # Get the document chunks by their IDs. We use the "selectinload" option to load
        # the related Document objects in the same query and being able later to access
        # the document title without additional queries (e.g. "chunk.document.title").
        dc_stmt = (
            select(DocumentChunk)
            .where(DocumentChunk.id.in_(chunk_ids))  # type: ignore
            .options(selectinload(DocumentChunk.document))  # type: ignore
        )

        dcs = session.exec(dc_stmt).all()

        # Sort the document chunks by the order of the IDs in the "chunk_ids" list and
        # return them.
        return sorted(dcs, key=lambda x: chunk_ids.index(x.id))
