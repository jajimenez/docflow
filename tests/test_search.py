"""Unit tests for docflow.search."""

from uuid import UUID
from unittest.mock import MagicMock, patch

import pytest

from docflow.db.models import DocumentChunk
from docflow.search import get_most_similar_chunks


class TestGetMostSimilarChunks:
    def test_limit_zero_raises(self):
        with pytest.raises(ValueError, match="Invalid limit"):
            get_most_similar_chunks("db_url", "api_url", 30, "model", "text", limit=0)

    def test_limit_negative_raises(self):
        with pytest.raises(ValueError, match="Invalid limit"):
            get_most_similar_chunks("db_url", "api_url", 30, "model", "text", limit=-1)

    def test_limit_above_max_raises(self):
        with pytest.raises(ValueError, match="Invalid limit"):
            get_most_similar_chunks(
                "db_url", "api_url", 30, "model", "text", limit=1001
            )

    def test_limit_non_integer_raises(self):
        with pytest.raises(ValueError, match="Invalid limit"):
            get_most_similar_chunks("db_url", "api_url", 30, "model", "text", limit="5")  # type: ignore

    def test_empty_embedding_raises(self):
        with patch("docflow.search.get_embedding", return_value=[]):
            with pytest.raises(ValueError, match="Invalid embedding"):
                get_most_similar_chunks("db_url", "api_url", 30, "model", "text")

    def test_non_numeric_embedding_raises(self):
        with patch("docflow.search.get_embedding", return_value=["a", "b", "c"]):
            with pytest.raises(ValueError, match="Invalid embedding"):
                get_most_similar_chunks("db_url", "api_url", 30, "model", "text")

    def test_returns_empty_list_when_no_chunks_found(self):
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.exec.return_value = iter([])  # No rows returned

        with (
            patch("docflow.search.get_embedding", return_value=[0.1, 0.2, 0.3]),
            patch("docflow.search.get_session", return_value=mock_session),
        ):
            result = get_most_similar_chunks("db_url", "api_url", 30, "model", "text")

        assert result == []

    def test_returns_chunks_sorted_by_similarity(self):
        id_a = UUID("aaaaaaaa-0000-0000-0000-000000000000")
        id_b = UUID("bbbbbbbb-0000-0000-0000-000000000000")

        chunk_a = MagicMock(spec=DocumentChunk)
        chunk_a.id = id_a
        chunk_b = MagicMock(spec=DocumentChunk)
        chunk_b.id = id_b

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        # First exec: similarity search returns IDs in similarity order [b, a]
        # Second exec: fetch by IDs returns [chunk_a, chunk_b] (any order)
        second_result = MagicMock()
        second_result.all.return_value = [chunk_a, chunk_b]

        mock_session.exec.side_effect = [
            iter([(id_b,), (id_a,)]),
            second_result,
        ]

        with (
            patch("docflow.search.get_embedding", return_value=[0.1, 0.2, 0.3]),
            patch("docflow.search.get_session", return_value=mock_session),
        ):
            result = get_most_similar_chunks("db_url", "api_url", 30, "model", "text")

        # chunk_b should come first because it was ranked higher by similarity search
        assert result[0].id == id_b
        assert result[1].id == id_a
