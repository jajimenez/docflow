"""Data models module."""

from uuid import UUID
from datetime import datetime
from enum import Enum

from sqlmodel import SQLModel, Field, Relationship, UniqueConstraint

from sqlalchemy import (
    CheckConstraint,
    Column,
    UUID as SA_UUID,
    Text,
    DateTime,
    Enum as SaEnum,
    ForeignKey,
    Index,
    text,
    func,
)

from docflow.db.types import Vector


# The following type of fields require an explicit Column definition with the
# "sa_column" attribute of the Field class:
#
#   - Fields with default values generated at the database server (e.g. "id",
#     "created_at" or "updated_at")
#   - Foreign fields
#   - Large text fields (e.g. "chunk_text"), so that they can be created as Text and not
#     Varchar.
#   - Custom types (e.g. "status", "source_type" or "embedding")


class DocumentStatus(str, Enum):
    """Document status."""

    pending = "pending"
    processing = "processing"
    processed = "processed"
    failed = "failed"


class DocumentSourceType(str, Enum):
    """Document source type."""

    pdf = "pdf"
    github = "github"
    azure_devops = "azure_devops"
    confluence = "confluence"


class Document(SQLModel, table=True):
    """Document model."""

    __tablename__ = "documents"  # type: ignore

    id: UUID | None = Field(
        sa_column=Column(
            SA_UUID(as_uuid=True),
            primary_key=True,
            server_default=text("uuid_generate_v4()"),
        )
    )

    source_type: DocumentSourceType = Field(
        sa_column=Column(
            SaEnum(DocumentSourceType, name="source_type"),
            nullable=False,
        )
    )

    # Local filesystem path (mounted volume). Set for PDF documents, null for remote
    # sources (GitHub, Confluence, Azure DevOps) that are identified by source_url
    # instead. PostgreSQL allows multiple nulls in a unique index, so the uniqueness
    # constraint still prevents duplicate PDF ingestion.
    source_file_path: str | None = Field(
        default=None, unique=True, min_length=1, max_length=500
    )

    # Original remote URL (e.g. Confluence page, GitHub blob, Azure DevOps wiki page).
    # null for locally-sourced documents such as PDFs. A URL is globally unique (it
    # cannot belong to two source types), so uniqueness is enforced on the field alone.
    # PostgreSQL allows multiple nulls in a unique index, so PDF documents are not
    # affected.
    source_url: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True, unique=True)
    )

    title: str = Field(min_length=1, max_length=200)

    status: DocumentStatus = Field(
        sa_column=Column(
            SaEnum(DocumentStatus, name="document_status"),
            nullable=False,
            server_default=text(f"'pending'"),
        ),
        default=DocumentStatus.pending,
    )

    created_at: datetime | None = Field(
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
        )
    )

    updated_at: datetime | None = Field(
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
        )
    )

    # Relationship: A document has 0, 1 or more document chunks.
    chunks: list["DocumentChunk"] = Relationship(
        back_populates="document", sa_relationship_kwargs={"cascade": "all"}
    )

    __table_args__ = (
        # Enforce the mutual exclusivity between source_file_path and source_url:
        #   - PDF documents must have a source_file_path and no source_url.
        #   - Remote documents must have a source_url and no source_file_path.
        # This guarantees source_file_path is never null for PDF documents and
        # source_url is never null for remote sources.
        CheckConstraint(
            "(source_type = 'pdf' "
            "AND source_file_path IS NOT NULL "
            "AND source_url IS NULL)"
            " OR "
            "(source_type != 'pdf' "
            "AND source_url IS NOT NULL "
            "AND source_file_path IS NULL)",
            name="check_document_source_fields",
        ),
    )


class DocumentChunk(SQLModel, table=True):
    """Document chunk model."""

    __tablename__ = "document_chunks"  # type: ignore

    id: UUID | None = Field(
        sa_column=Column(
            SA_UUID(as_uuid=True),
            primary_key=True,
            server_default=text("uuid_generate_v4()"),
        )
    )

    document_id: UUID | None = Field(
        sa_column=Column(
            SA_UUID(as_uuid=True),
            ForeignKey("documents.id", ondelete="cascade"),
            nullable=False,
        )
    )

    chunk_index: int
    chunk_text: str = Field(sa_column=Column(Text, nullable=False))
    embedding: list[float] = Field(sa_column=Column(Vector, nullable=False))

    # Relationship: Each document chunk belongs to one document.
    document: Document = Relationship(back_populates="chunks")

    # Constraints: The combination of Document ID and Chunk Index is unique.
    # Indexes: We need an index for the "embedding" field to perform efficient
    # similarity search. We use HNSW (Hierarchical Navigable Small World), which is a
    # graph-based algorithm for approximate nearest neighbor (ANN) search in
    # high-dimensional vector spaces. We use the "vector_cosine_ops" operator class
    # (metric) to search for vectors using the cosine distance. This operator class is
    # the right choice when using an embedding model that generates normalized vectors
    # because the cosine similarity measures angular similarity, ignoring vector
    # magnitude.
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="unique_document_chunk"),
        Index(
            "idx_document_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
