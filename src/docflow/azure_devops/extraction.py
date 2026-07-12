"""Azure DevOps Wiki extraction module.

This module provides low-level functions for listing the pages of an Azure DevOps wiki
and extracting their Markdown content.

Azure DevOps wikis store pages as Markdown files in a backing Git repository, so content
is already in Markdown format — no HTML-to-Markdown conversion is needed.
"""

import re
import logging
from urllib.parse import unquote

from docflow.azure_devops.auth import get_client


# Matches the Azure DevOps wiki page URL, for both cloud and on-premises:
#   Cloud:    https://dev.azure.com/{org}/{project}/_wiki/wikis/{wiki}/{pageId}[/...]
#   On-prem:  https://{server}/{collection}/{project}/_wiki/wikis/{wiki}/{pageId}[/...]
#
# Captured groups: (org_url, project, wiki_identifier, page_id)
WIKI_PAGE_URL_PATTERN = re.compile(
    r"(https?://[^/]+/[^/]+)/([^/]+)/_wiki/wikis/([^/]+)/(\d+)"
)

WIKI_PAGES_FOUND = "Found {} page(s) in wiki '{}' of project '{}'"

logger = logging.getLogger(__name__)


def _collect_pages(page) -> list:
    """Recursively collect all wiki pages from a page tree into a flat list."""
    if page is None:
        return []

    pages = [page]

    for sub_page in page.sub_pages or []:
        pages.extend(_collect_pages(sub_page))

    return pages


def get_wiki_pages(
    org_url: str,
    project: str,
    wiki: str,
    pat: str | None = None,
) -> list:
    """List all pages of an Azure DevOps wiki.

    Fetches the full page tree in a single API call (using ``recursionLevel=full``)
    and flattens it into a list of ``WikiPage`` objects. Each page object contains its
    ``path``, ``remote_url`` and ``id`` but not its content; content is fetched
    separately in ``extract_text``.

    Args:
        org_url: Base URL of the Azure DevOps organization, e.g.
            ``"https://dev.azure.com/org"``.
        project: Project name or ID (e.g. ``"Project"``).
        wiki: Wiki name or ID (e.g. ``"Project.wiki"``).
        pat: Personal Access Token for authentication (optional).

    Returns:
        Flat list of ``WikiPage`` objects (structure only, no content).
    """
    client = get_client(org_url, pat)

    response = client.get_page(
        project=project,
        wiki_identifier=wiki,
        recursion_level="full",
        include_content=False,
    )

    pages = _collect_pages(response.page) if response and response.page else []
    logger.info(WIKI_PAGES_FOUND.format(len(pages), wiki, project))

    return pages


def get_page_url(page) -> str:
    """Return the URL of a wiki page.

    Args:
        page: ``WikiPage`` object as returned by ``get_wiki_pages``.

    Returns:
        URL of the page (``page.remote_url``).
    """
    return page.remote_url


def get_page_title(page) -> str:
    """Derive the display title of a wiki page from its path.

    Azure DevOps wiki page paths use hyphens in place of spaces (e.g.
    ``/Architecture/Getting-Started`` -> ``"Getting Started"``). This function takes the
    last segment of the path, URL-decodes it and replaces hyphens with spaces to
    reconstruct the original title.

    Args:
        page: ``WikiPage`` object as returned by ``get_wiki_pages``.

    Returns:
        Human-readable title of the page.
    """
    path = page.path or "/"
    segment = path.rstrip("/").split("/")[-1]

    if not segment:
        # Root page ("/") — fall back to the wiki name embedded in remote_url, or just
        # use "Home" as a safe default.
        return "Home"

    return unquote(segment).replace("-", " ")


def _parse_page_url(page_url: str) -> tuple[str, str, str, int]:
    """Parse a wiki page URL into its components.

    Args:
        page_url: URL of the wiki page (the ``remote_url`` value stored as the
            document's source URL).

    Returns:
        Tuple of ``(org_url, project, wiki_identifier, page_id)``.

    Raises:
        ValueError: If the URL does not match the expected Azure DevOps wiki format.
    """
    match = WIKI_PAGE_URL_PATTERN.match(page_url)

    if not match:
        raise ValueError(
            f'Cannot parse Azure DevOps wiki page URL: "{page_url}". '
            "Expected format: https://dev.azure.com/{org}/{project}/_wiki/wikis/"
            "{wiki}/{pageId}[/{pageName}]"
        )

    org_url, project, wiki_identifier, page_id = match.groups()
    return org_url, project, wiki_identifier, int(page_id)


def extract_text(page_url: str, pat: str | None = None) -> str:
    """Fetch the Markdown content of a single Azure DevOps wiki page.

    The organization URL, project name, wiki identifier and page ID are all derived from
    the ``page_url`` (the ``remote_url`` stored as the document's source URL), so no
    additional parameters are required beyond the PAT for authentication.

    Args:
        page_url: URL of the wiki page (the ``remote_url`` stored as the document's
            source URL).
        pat: Personal Access Token for authentication (optional).

    Returns:
        Markdown content of the page.

    Raises:
        ValueError: If the URL cannot be parsed or the API returns no content.
    """
    org_url, project, wiki_identifier, page_id = _parse_page_url(page_url)
    wiki_client = get_client(org_url, pat)

    response = wiki_client.get_page_by_id(
        project=project,
        wiki_identifier=wiki_identifier,
        id=page_id,
        include_content=True,
    )

    if not response or not response.page or response.page.content is None:
        raise ValueError(f'No content returned for page: "{page_url}"')

    return response.page.content
