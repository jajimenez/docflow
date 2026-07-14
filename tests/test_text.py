"""Unit tests for docflow.text."""

from unittest.mock import MagicMock, patch

import pytest
from requests import HTTPError

from docflow.text import convert_html_to_markdown, get_embedding, split_text


class TestConvertHtmlToMarkdown:
    def test_paragraph(self):
        result = convert_html_to_markdown("<p>Hello World</p>")
        assert "Hello World" in result

    def test_heading(self):
        result = convert_html_to_markdown("<h1>Title</h1>")
        assert "Title" in result

    def test_bold(self):
        result = convert_html_to_markdown("<strong>bold text</strong>")
        assert "bold text" in result

    def test_empty_string_returns_empty(self):
        assert convert_html_to_markdown("") == ""

    def test_none_returns_empty(self):
        assert convert_html_to_markdown(None) == ""  # type: ignore

    def test_nested_elements(self):
        html = "<div><h2>Section</h2><p>Content here.</p></div>"
        result = convert_html_to_markdown(html)
        assert "Section" in result
        assert "Content here." in result


class TestSplitText:
    def test_short_text_returns_single_chunk(self):
        chunks = split_text("Hello World", chunk_size=1000, chunk_overlap=0)
        assert chunks == ["Hello World"]

    def test_long_text_is_split_into_multiple_chunks(self):
        # 500 repetitions of "word " = 2500 chars, well above chunk_size=100
        text = "word " * 500
        chunks = split_text(text, chunk_size=100, chunk_overlap=0)
        assert len(chunks) > 1

    def test_empty_text_returns_empty_list(self):
        assert split_text("", chunk_size=100, chunk_overlap=0) == []

    def test_zero_chunk_size_raises(self):
        with pytest.raises(ValueError, match="Chunk size must be greater than 0"):
            split_text("hello", chunk_size=0)

    def test_negative_chunk_size_raises(self):
        with pytest.raises(ValueError, match="Chunk size must be greater than 0"):
            split_text("hello", chunk_size=-10)

    def test_negative_chunk_overlap_raises(self):
        with pytest.raises(ValueError, match="Chunk overlap must be 0 or greater"):
            split_text("hello", chunk_size=100, chunk_overlap=-1)

    def test_default_parameters_produce_list(self):
        text = "# Title\n\nSome content paragraph."
        chunks = split_text(text)
        assert isinstance(chunks, list)
        assert len(chunks) >= 1

    def test_each_chunk_does_not_exceed_chunk_size(self):
        text = "word " * 1000  # 5000 chars
        chunk_size = 200
        chunks = split_text(text, chunk_size=chunk_size, chunk_overlap=0)
        for chunk in chunks:
            assert len(chunk) <= chunk_size


class TestGetEmbedding:
    def test_returns_embedding_on_success(self):
        expected = [0.1, 0.2, 0.3]
        mock_response = MagicMock()
        mock_response.json.return_value = {"embedding": expected}
        mock_response.raise_for_status.return_value = None

        with patch("docflow.text.requests.post", return_value=mock_response):
            result = get_embedding(
                "http://localhost:11434/api/embeddings", 30, "nomic-embed-text", "hello"
            )

        assert result == expected

    def test_raises_on_http_error(self):
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = HTTPError("500 Server Error")

        with patch("docflow.text.requests.post", return_value=mock_response):
            with pytest.raises(HTTPError):
                get_embedding(
                    "http://localhost:11434/api/embeddings",
                    30,
                    "nomic-embed-text",
                    "hello",
                )

    def test_posts_correct_payload(self):
        api_url = "http://ollama:11434/api/embeddings"
        mock_response = MagicMock()
        mock_response.json.return_value = {"embedding": [0.1]}
        mock_response.raise_for_status.return_value = None

        with patch(
            "docflow.text.requests.post",
            return_value=mock_response,
        ) as mock_post:
            get_embedding(api_url, 30, "my-model", "some text")

        mock_post.assert_called_once_with(
            api_url,
            json={"model": "my-model", "prompt": "some text"},
            timeout=30,
        )
