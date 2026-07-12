"""Azure DevOps Wiki authentication module.

This module provides a factory function for creating an Azure DevOps Wiki API client
from an organization URL and an optional Personal Access Token (PAT).

This module is intentionally Airflow-agnostic: it receives plain values so that the
credentials can be resolved by the DAG from Airflow connections or secrets and passed
in.
"""

from azure.devops.connection import Connection
from azure.devops.v7_1.wiki.wiki_client import WikiClient
from msrest.authentication import BasicAuthentication


def get_client(org_url: str, pat: str | None = None) -> WikiClient:
    """Create an Azure DevOps Wiki client.

    Supports Personal Access Token (PAT) authentication and, when no PAT is provided,
    anonymous access (suitable only for public projects or internal networks that do not
    require authentication).

    Args:
        org_url: Base URL of the Azure DevOps organization, e.g.
            ``"https://dev.azure.com/org"``.
        pat: Personal Access Token for authentication (optional). Leave empty for
            anonymous access.

    Returns:
        Azure DevOps ``WikiClient`` instance.
    """
    if pat:
        credentials = BasicAuthentication("", pat)
        connection = Connection(base_url=org_url, creds=credentials)
    else:
        connection = Connection(base_url=org_url)

    return connection.clients.get_wiki_client()
