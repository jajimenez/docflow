"""Confluence text extraction module.

This module contains the low-level access to Confluence page and space data: listing
the pages of a space, building page URLs and extracting the text of a page. The creation
of the API client lives in ``docflow.confluence.auth``.
"""

import logging
import re
from urllib.parse import urlparse

from atlassian import Confluence

from docflow.confluence.auth import get_client
from docflow.text import convert_html_to_markdown


# Number of pages requested per Confluence API call (pagination batch size).
PAGE_BATCH_SIZE = 50

# Pattern to extract the numeric page ID from a Confluence page URL. It matches both the
# Cloud form (".../pages/12345/...") and the Server/Data Center form
# (".../viewpage.action?pageId=12345").
PAGE_ID_PATTERN = re.compile(r"(?:/pages/|pageId=)(\d+)")

# Messages
SPACE_PAGES_FOUND = "{} page(s) found in Confluence space {}"

# Logger
logger = logging.getLogger(__name__)


def get_space_pages(client: Confluence, space_key: str) -> list[dict]:
    """Get all the current pages of a Confluence space.

    The pages are fetched in batches (with pagination). Only the basic fields (including
    the page ID and links) are retrieved; the body is not fetched here, it is downloaded
    when the text of a page is extracted (see ``extract_text``).

    Args:
        client: Confluence API client.
        space_key: Key of the Confluence space.

    Returns:
        List of Confluence page objects.
    """
    pages: list[dict] = []
    start = 0

    while True:
        batch = client.get_all_pages_from_space(
            space=space_key,
            start=start,
            limit=PAGE_BATCH_SIZE,
            status="current",
        )

        if not batch:
            break

        pages.extend(batch)

        # Last page of results reached
        if len(batch) < PAGE_BATCH_SIZE:
            break

        start += PAGE_BATCH_SIZE

    logger.info(SPACE_PAGES_FOUND.format(len(pages), space_key))

    return pages


def get_page_url(page: dict, base_url: str) -> str:
    """Build the URL of a Confluence page.

    The URL is guaranteed to contain the page ID, so that the page can be downloaded
    later (during processing) using only its URL.

    Args:
        page: Confluence page object.
        base_url: Base URL of the Confluence instance, used as a fallback when the page
            object does not contain a base link.

    Returns:
        URL of the page.
    """
    page_id = page.get("id")
    links = page.get("_links", {})
    base = links.get("base") or base_url.rstrip("/")
    webui = links.get("webui", "")
    url = f"{base}{webui}"

    # Some Confluence instances (e.g. Server/Data Center) return a web URL that does not
    # contain the page ID (e.g. "/display/SPACE/Title"). In that case, build a URL that
    # does, so the page can be fetched later using only its URL.
    if not PAGE_ID_PATTERN.search(url):
        url = f"{base}/pages/viewpage.action?pageId={page_id}"

    return url


def _get_page_id(page_url: str) -> str:
    """Extract the numeric page ID from a Confluence page URL.

    Args:
        page_url: URL of the Confluence page.

    Returns:
        Page ID.
    """
    match = PAGE_ID_PATTERN.search(page_url)

    if not match:
        raise ValueError(f'Could not determine the page ID from the URL "{page_url}"')

    return match.group(1)


def _get_base_url(page_url: str) -> str:
    """Derive the base URL (scheme and host) from a Confluence page URL.

    Args:
        page_url: URL of the Confluence page.

    Returns:
        Base URL of the Confluence instance.
    """
    parsed_url = urlparse(page_url)

    if not parsed_url.scheme or not parsed_url.netloc:
        raise ValueError(f'Invalid Confluence page URL: "{page_url}"')

    return f"{parsed_url.scheme}://{parsed_url.netloc}"


def extract_text(
    page_url: str,
    base_url: str | None = None,
    username: str | None = None,
    password: str | None = None,
    token: str | None = None,
    verify_ssl: bool = True,
    cloud: bool = False,
) -> str:
    """Download a Confluence page and extract its text in Markdown format.

    The page ID is derived from the page URL. The base URL of the instance is taken from
    ``base_url`` when provided, which allows Confluence to be served under a context
    path (e.g. "https://intranet.example.com/confluence"); otherwise it is derived from
    the page URL (scheme and host).

    The storage-format (XHTML) body of the page is downloaded from the Confluence API
    and converted to Markdown.

    Args:
        page_url: Web URL of the Confluence page (e.g.
            "https://confluence.example.com/pages/viewpage.action?pageId=12345").
        base_url: Base URL of the Confluence instance (optional). Set it when the
            instance is served under a context path (e.g.
            "https://intranet.example.com/confluence").
        username: User name for basic authentication (optional).
        password: Password or API token for basic authentication (optional).
        token: Personal access token for token-based authentication (optional).
        verify_ssl: Whether to verify the TLS certificate of the server.
        cloud: Whether the instance is Confluence Cloud (True) or Server/Data Center
            (False).

    Returns:
        Page text in Markdown format.
    """
    base_url = base_url or _get_base_url(page_url)
    page_id = _get_page_id(page_url)

    client = get_client(
        base_url,
        username=username,
        password=password,
        token=token,
        verify_ssl=verify_ssl,
        cloud=cloud,
    )

    page = client.get_page_by_id(page_id, expand="body.storage")

    # Storage-format (XHTML) body of the page
    body = page.get("body", {}).get("storage", {}).get("value", "")  # type: ignore

    return convert_html_to_markdown(body)
