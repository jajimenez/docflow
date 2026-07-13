"""Azure DevOps Wiki extraction module.

This module provides low-level functions for listing the pages of an Azure DevOps wiki
and extracting their Markdown content.

Azure DevOps wikis store pages as Markdown files in a backing Git repository, so content
is already in Markdown format — no HTML-to-Markdown conversion is needed.
"""

import logging
from urllib.parse import unquote, urlsplit, parse_qs

from docflow.azure_devops.auth import get_client


# Marker that separates the "{org_url}/{project}" prefix from the "{wiki}[/{pageId}]"
# suffix in an Azure DevOps wiki page URL, across all URL patterns (see
# ``_parse_page_url`` for the exact patterns handled).
WIKI_PATH_MARKER = "/_wiki/wikis/"

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


def _parse_page_url(page_url: str) -> tuple[str, str, str, int | None, str | None]:
    """Parse a wiki page URL into its components.

    Handles the different URL patterns Azure DevOps uses:

    - Cloud:
        https://dev.azure.com/{org}/{project}/_wiki/wikis/{wiki}/{pageId}[/{pageName}]
    - On-premises:
        https://{server}/{collection}/{project}/_wiki/wikis/{wiki}/{pageId}[/{pageName}]
    - Legacy:
        https://{org}.visualstudio.com/{project}/_wiki/wikis/{wiki}?pagePath={pagePath}

    In all cases, the "{org_url}/{project}" prefix and the "{wiki}" identifier are split
    around the "/_wiki/wikis/" marker (the project is always the last path segment
    before it). The page is then located either by a numeric page ID (modern URLs) or by
    the URL-encoded "pagePath" query parameter (legacy URLs).

    Args:
        page_url: URL of the wiki page (the ``remote_url`` value stored as the
            document's source URL).

    Returns:
        Tuple of ``(org_url, project, wiki_identifier, page_id, page_path)``. One of
        ``page_id`` or ``page_path`` is set; the other is ``None``.

    Raises:
        ValueError: If the URL does not match the expected Azure DevOps wiki format.
    """
    f1 = (
        "https://dev.azure.com/{org}/{project}/_wiki/wikis/{wiki}/{pageId}[/{pageName}]"
    )

    f2 = (
        "https://{server}/{collection}/{project}/_wiki/wikis/{wiki}/{pageId}"
        "[/{pageName}]"
    )

    f3 = (
        "https://{org}.visualstudio.com/{project}/_wiki/wikis/{wiki}"
        "?pagePath={pagePath}"
    )

    error = ValueError(
        f'Cannot parse Azure DevOps wiki page URL: "{page_url}". '
        f'Expected format: "{f1}" or "{f2}" or "{f3}"'
    )

    split = urlsplit(page_url)
    base = f"{split.scheme}://{split.netloc}{split.path}"
    marker_index = base.find(WIKI_PATH_MARKER)

    if marker_index == -1:
        raise error

    # "{org_url}/{project}" - The project is the last path segment before the marker
    org_url, _, project = base[:marker_index].rpartition("/")

    # "{wiki}[/{pageId}][/{pageName}]" - Everything after the marker
    suffix_segments = base[marker_index + len(WIKI_PATH_MARKER):].split("/")
    wiki_identifier = suffix_segments[0]

    if not org_url or not project or not wiki_identifier:
        raise error

    # Modern URLs carry a numeric page ID as the segment right after the wiki
    if len(suffix_segments) > 1 and suffix_segments[1].isdigit():
        return org_url, project, wiki_identifier, int(suffix_segments[1]), None

    # Legacy URLs identify the page via the "pagePath" query parameter (parse_qs already
    # URL-decodes it)
    page_path_values = parse_qs(split.query).get("pagePath")

    if page_path_values and page_path_values[0]:
        return org_url, project, wiki_identifier, None, page_path_values[0]

    raise error


def extract_text(page_url: str, pat: str | None = None) -> str:
    """Fetch the Markdown content of a single Azure DevOps wiki page.

    The organization URL, project name, wiki identifier and page ID (or page path, for
    legacy URLs) are all derived from the ``page_url`` (the ``remote_url`` stored as the
    document's source URL).

    Args:
        page_url: URL of the wiki page (the ``remote_url`` stored as the document's
            source URL).
        pat: Personal Access Token for authentication (optional).

    Returns:
        Markdown content of the page.

    Raises:
        ValueError: If the URL cannot be parsed or the API returns no content.
    """
    org_url, project, wiki_identifier, page_id, page_path = _parse_page_url(page_url)
    wiki_client = get_client(org_url, pat)

    if page_id is not None:
        # Model URLs: fetch by numeric ID
        response = wiki_client.get_page_by_id(
            project=project,
            wiki_identifier=wiki_identifier,
            id=page_id,
            include_content=True,
        )
    else:
        # Legacy URLs: fetch by page path
        response = wiki_client.get_page(
            project=project,
            wiki_identifier=wiki_identifier,
            path=page_path,
            include_content=True,
        )

    if not response or not response.page or response.page.content is None:
        raise ValueError(f'No content returned for page: "{page_url}"')

    return response.page.content
