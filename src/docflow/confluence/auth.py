"""Confluence authentication module.

This module builds a Confluence API client, selecting the authentication method based on
the provided credentials (personal access token, basic authentication or anonymous
access).
"""

from atlassian import Confluence


def get_client(
    url: str,
    username: str | None = None,
    password: str | None = None,
    token: str | None = None,
    verify_ssl: bool = True,
    cloud: bool = False,
) -> Confluence:
    """Get a Confluence API client.

    The authentication method is selected based on the provided credentials:

        - If a personal access token (``token``) is provided, token-based
          authentication is used.
        - Else, if ``username`` and ``password`` (or API token as password) are
          provided, basic authentication is used.
        - Else, the client connects anonymously (no authentication). This is useful when
          Confluence is readable from within the company network without logging in.

    Args:
        url: Base URL of the Confluence instance (e.g.
            "https://confluence.example.com").
        username: User name for basic authentication (optional).
        password: Password or API token for basic authentication (optional).
        token: Personal access token for token-based authentication (optional).
        verify_ssl: Whether to verify the TLS certificate of the server.
        cloud: Whether the instance is Confluence Cloud (True) or Server/Data Center
            (False). This changes the REST API base path used by the client.

    Returns:
        Confluence API client.
    """
    if token:
        return Confluence(url=url, token=token, verify_ssl=verify_ssl, cloud=cloud)

    if username and password:
        return Confluence(
            url=url,
            username=username,
            password=password,
            verify_ssl=verify_ssl,
            cloud=cloud,
        )

    # Anonymous access
    return Confluence(url=url, verify_ssl=verify_ssl, cloud=cloud)
