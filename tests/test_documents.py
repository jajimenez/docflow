"""Unit tests for docflow.documents."""

from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

from docflow.db.models import Document, DocumentChunk, DocumentStatus
from docflow.documents import get_document, process_document, save_document


_DOC_ID = UUID("550e8400-e29b-41d4-a716-446655440000")


class TestGetDocument:
    def test_by_id_returns_document(self):
        mock_doc = MagicMock(spec=Document)
        mock_session = MagicMock()
        mock_session.exec.return_value.first.return_value = mock_doc

        result = get_document(mock_session, id=_DOC_ID)

        assert result is mock_doc
        mock_session.exec.assert_called_once()

    def test_by_source_file_path_returns_document(self):
        mock_doc = MagicMock(spec=Document)
        mock_session = MagicMock()
        mock_session.exec.return_value.first.return_value = mock_doc

        result = get_document(mock_session, source_file_path="/docs/file.pdf")

        assert result is mock_doc

    def test_by_source_url_returns_document(self):
        mock_doc = MagicMock(spec=Document)
        mock_session = MagicMock()
        mock_session.exec.return_value.first.return_value = mock_doc

        result = get_document(mock_session, source_url="https://example.com/page")

        assert result is mock_doc

    def test_returns_none_when_not_found(self):
        mock_session = MagicMock()
        mock_session.exec.return_value.first.return_value = None

        result = get_document(mock_session, id=_DOC_ID)

        assert result is None

    def test_no_criteria_raises(self):
        mock_session = MagicMock()

        with pytest.raises(ValueError, match='"id", "source_file_path" or "source_url"'):
            get_document(mock_session)


class TestSaveDocument:
    def test_new_document_is_merged_and_id_returned(self):
        doc = MagicMock(spec=Document)
        doc.id = None  # New document

        merged_doc = MagicMock(spec=Document)
        merged_doc.id = _DOC_ID

        mock_session = MagicMock()
        mock_session.merge.return_value = merged_doc

        result = save_document(mock_session, doc)

        mock_session.merge.assert_called_once_with(doc)
        mock_session.commit.assert_called()
        mock_session.refresh.assert_called_once_with(merged_doc)

        assert result == _DOC_ID

    def test_existing_document_is_updated(self):
        doc = MagicMock(spec=Document)
        doc.id = _DOC_ID  # Existing document

        existing = MagicMock(spec=Document)
        merged_doc = MagicMock(spec=Document)
        merged_doc.id = _DOC_ID

        mock_session = MagicMock()
        mock_session.get.return_value = existing
        mock_session.merge.return_value = merged_doc

        result = save_document(mock_session, doc)

        mock_session.get.assert_called_once_with(Document, _DOC_ID)
        mock_session.merge.assert_called_once_with(doc)

        assert result == _DOC_ID

    def test_updating_nonexistent_document_raises(self):
        doc = MagicMock(spec=Document)
        doc.id = _DOC_ID  # Has an ID, but document doesn't exist in DB

        mock_session = MagicMock()
        mock_session.get.return_value = None  # Not found in DB

        with pytest.raises(ValueError, match=str(_DOC_ID)):
            save_document(mock_session, doc)

        mock_session.merge.assert_not_called()


class TestProcessDocument:
    def _make_mock_session(self, doc):
        mock_session = MagicMock()
        mock_session.get.return_value = doc

        return mock_session

    def test_not_found_raises(self):
        mock_session = MagicMock()
        mock_session.get.return_value = None

        with pytest.raises(ValueError, match=str(_DOC_ID)):
            process_document(mock_session, _DOC_ID, lambda d: "")

    def test_success_sets_status_to_processed(self):
        mock_doc = MagicMock()
        mock_doc.id = _DOC_ID
        mock_doc.chunks = []

        mock_session = self._make_mock_session(mock_doc)

        with (
            patch("docflow.documents.settings") as mock_settings,
            patch("docflow.documents.split_text", return_value=["chunk one"]),
            patch("docflow.documents.get_embedding", return_value=[0.1, 0.2, 0.3]),
        ):
            mock_settings.chunk_size = 100
            mock_settings.chunk_overlap = 0
            mock_settings.embeddings_api_url = "http://localhost:11434/api/embeddings"
            mock_settings.embeddings_api_timeout = 30
            mock_settings.embeddings_model = "nomic-embed-text"

            process_document(mock_session, _DOC_ID, lambda d: "# Title\n\nContent.")

        assert mock_doc.status == DocumentStatus.processed
        mock_session.add.assert_called_once()

    def test_success_deletes_existing_chunks_before_processing(self):
        chunk_a = MagicMock(spec=DocumentChunk)
        chunk_b = MagicMock(spec=DocumentChunk)

        mock_doc = MagicMock()
        mock_doc.id = _DOC_ID
        mock_doc.chunks = [chunk_a, chunk_b]

        mock_session = self._make_mock_session(mock_doc)

        with (
            patch("docflow.documents.settings") as mock_settings,
            patch("docflow.documents.split_text", return_value=["chunk"]),
            patch("docflow.documents.get_embedding", return_value=[0.1]),
        ):
            mock_settings.chunk_size = 100
            mock_settings.chunk_overlap = 0
            mock_settings.embeddings_api_url = "http://localhost"
            mock_settings.embeddings_api_timeout = 30
            mock_settings.embeddings_model = "model"

            process_document(mock_session, _DOC_ID, lambda d: "content")

        mock_session.delete.assert_any_call(chunk_a)
        mock_session.delete.assert_any_call(chunk_b)

    def test_extraction_failure_sets_status_to_failed_and_reraises(self):
        mock_doc = MagicMock()
        mock_doc.id = _DOC_ID
        mock_doc.chunks = []

        mock_session = self._make_mock_session(mock_doc)

        def failing_extract(doc):
            raise RuntimeError("Extraction error")

        with patch("docflow.documents.settings") as mock_settings:
            mock_settings.chunk_size = 100
            mock_settings.chunk_overlap = 0

            with pytest.raises(RuntimeError, match="Extraction error"):
                process_document(mock_session, _DOC_ID, failing_extract)

        assert mock_doc.status == DocumentStatus.failed
        mock_session.rollback.assert_called()
