"""Unit tests for docflow.azure_devops.extraction."""

from unittest.mock import MagicMock

import pytest

from docflow.azure_devops.extraction import (
    _collect_pages,
    _parse_page_url,
    get_page_title,
    get_page_url,
)


class TestCollectPages:
    def test_none_returns_empty_list(self):
        assert _collect_pages(None) == []

    def test_single_page_with_no_subpages(self):
        page = MagicMock()
        page.sub_pages = []
        result = _collect_pages(page)
        assert result == [page]

    def test_collects_direct_subpages(self):
        page_2 = MagicMock()
        page_2.sub_pages = []

        page_1 = MagicMock()
        page_1.sub_pages = [page_2]

        result = _collect_pages(page_1)

        assert len(result) == 2
        assert page_1 in result
        assert page_2 in result

    def test_collects_deeply_nested_pages(self):
        page_3 = MagicMock()
        page_3.sub_pages = []

        page_2 = MagicMock()
        page_2.sub_pages = [page_3]

        page_1 = MagicMock()
        page_1.sub_pages = [page_2]

        result = _collect_pages(page_1)

        assert len(result) == 3
        assert page_1 in result
        assert page_2 in result
        assert page_3 in result

    def test_page_with_none_subpages(self):
        page = MagicMock()
        page.sub_pages = None

        result = _collect_pages(page)
        assert result == [page]


class TestGetPageTitle:
    def test_simple_path(self):
        page = MagicMock()
        page.path = "/Architecture/Getting-Started"

        assert get_page_title(page) == "Getting Started"

    def test_url_encoded_spaces(self):
        page = MagicMock()
        page.path = "/Docs/Test%20Page"

        assert get_page_title(page) == "Test Page"

    def test_root_path_returns_home(self):
        page = MagicMock()
        page.path = "/"

        assert get_page_title(page) == "Home"

    def test_none_path_returns_home(self):
        page = MagicMock()
        page.path = None

        assert get_page_title(page) == "Home"

    def test_top_level_page(self):
        page = MagicMock()
        page.path = "/Welcome"

        assert get_page_title(page) == "Welcome"

    def test_hyphen_replaced_by_space(self):
        page = MagicMock()
        page.path = "/Section/Sub-Section-Title"

        assert get_page_title(page) == "Sub Section Title"


class TestGetPageUrl:
    def test_returns_remote_url(self):
        page = MagicMock()
        page.remote_url = "https://dev.azure.com/org/proj/_wiki/wikis/proj.wiki/1/Home"

        assert get_page_url(page) == page.remote_url


class TestParsePageUrl:
    def test_azure_devops_cloud_url(self):
        url = "https://dev.azure.com/myorg/project/_wiki/wikis/project.wiki/42/Home"
        org_url, project, wiki, page_id, page_path = _parse_page_url(url)

        assert org_url == "https://dev.azure.com/myorg"
        assert project == "project"
        assert wiki == "project.wiki"
        assert page_id == 42
        assert page_path is None

    def test_on_premises_url(self):
        url = (
            "https://example.com/DefaultCollection/project"
            "/_wiki/wikis/project.wiki/7/docs"
        )

        org_url, project, wiki, page_id, page_path = _parse_page_url(url)

        assert org_url == "https://example.com/DefaultCollection"
        assert project == "project"
        assert wiki == "project.wiki"
        assert page_id == 7
        assert page_path is None

    def test_legacy_visualstudio_url(self):
        url = (
            "https://myorg.visualstudio.com/project"
            "/_wiki/wikis/project.wiki?pagePath=/Home/Sub-Page"
        )
        org_url, project, wiki, page_id, page_path = _parse_page_url(url)

        assert org_url == "https://myorg.visualstudio.com"
        assert project == "project"
        assert wiki == "project.wiki"
        assert page_id is None
        assert page_path == "/Home/Sub-Page"

    def test_url_without_wiki_marker_raises(self):
        with pytest.raises(ValueError, match="Cannot parse Azure DevOps wiki page URL"):
            _parse_page_url("https://example.com/not/a/wiki/url")

    def test_url_with_page_name_segment(self):
        # Modern cloud URL with an optional page-name segment after the ID
        url = (
            "https://dev.azure.com/org/Proj/_wiki/wikis/Proj.wiki/5/Architecture-Overview"
        )

        _, _, _, page_id, page_path = _parse_page_url(url)

        assert page_id == 5
        assert page_path is None
