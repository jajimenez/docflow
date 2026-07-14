"""Unit tests for docflow.confluence.extraction."""

from unittest.mock import MagicMock

import pytest

from docflow.confluence.extraction import (
    PAGE_BATCH_SIZE,
    _get_base_url,
    _get_page_id,
    get_page_url,
    get_space_pages,
)


class TestGetPageUrl:
    def test_returns_base_plus_webui_when_url_contains_page_id(self):
        page = {
            "id": "12345",
            "_links": {
                "base": "https://wiki.example.com",
                "webui": "/pages/12345/page",
            },
        }

        url = get_page_url(page, "https://wiki.example.com")
        assert url == "https://wiki.example.com/pages/12345/page"

    def test_falls_back_to_base_url_when_links_has_no_base(self):
        page = {
            "id": "12345",
            "_links": {"webui": "/pages/12345/title"},
        }

        url = get_page_url(page, "https://wiki.example.com")
        assert url == "https://wiki.example.com/pages/12345/title"

    def test_adds_page_id_when_webui_lacks_id(self):
        # Confluence Server may return a display URL without the page ID
        page = {
            "id": "99999",
            "_links": {
                "base": "https://wiki.example.com",
                "webui": "/display/space/title",
            },
        }

        url = get_page_url(page, "https://wiki.example.com")
        assert "99999" in url

    def test_uses_base_url_param_as_fallback_when_links_has_no_base(self):
        # When _links has no "base" key, the base_url parameter is used (stripped)
        page = {
            "id": "1",
            "_links": {"webui": "/pages/1/home"},  # no "base" key
        }

        url = get_page_url(page, "https://wiki.example.com/")

        # base_url trailing slash is stripped before use
        assert url == "https://wiki.example.com/pages/1/home"


class TestGetPageId:
    def test_cloud_url_with_pages_segment(self):
        url = "https://mycompany.atlassian.net/wiki/spaces/DEV/pages/12345/page"
        assert _get_page_id(url) == "12345"

    def test_server_viewpage_action(self):
        url = "https://wiki.example.com/pages/viewpage.action?pageId=67890"
        assert _get_page_id(url) == "67890"

    def test_url_without_page_id_raises(self):
        with pytest.raises(ValueError, match="Could not determine the page ID"):
            _get_page_id("https://wiki.example.com/display/space/page")


class TestGetBaseUrl:
    def test_extracts_scheme_and_host(self):
        url = "https://wiki.example.com/pages/viewpage.action?pageId=123"
        assert _get_base_url(url) == "https://wiki.example.com"

    def test_relative_url_raises(self):
        with pytest.raises(ValueError, match="Invalid Confluence page URL"):
            _get_base_url("/relative/path")

    def test_missing_scheme_raises(self):
        with pytest.raises(ValueError, match="Invalid Confluence page URL"):
            _get_base_url("wiki.example.com/pages/1")


class TestGetSpacePages:
    def test_returns_all_pages_across_two_batches(self):
        first_batch = [{"id": str(i)} for i in range(PAGE_BATCH_SIZE)]

        second_batch = [
            {"id": str(i)} for i in range(PAGE_BATCH_SIZE, PAGE_BATCH_SIZE + 10)
        ]

        mock_client = MagicMock()

        mock_client.get_all_pages_from_space.side_effect = [
            first_batch,
            second_batch,
        ]

        pages = get_space_pages(mock_client, "space")
        assert len(pages) == PAGE_BATCH_SIZE + 10

    def test_single_partial_batch_stops_pagination(self):
        partial_batch = [{"id": "1"}, {"id": "2"}]

        mock_client = MagicMock()
        mock_client.get_all_pages_from_space.return_value = partial_batch

        pages = get_space_pages(mock_client, "space")

        assert len(pages) == 2
        assert mock_client.get_all_pages_from_space.call_count == 1

    def test_empty_space_returns_empty_list(self):
        mock_client = MagicMock()
        mock_client.get_all_pages_from_space.return_value = []

        pages = get_space_pages(mock_client, "space")

        assert pages == []
        assert mock_client.get_all_pages_from_space.call_count == 1
