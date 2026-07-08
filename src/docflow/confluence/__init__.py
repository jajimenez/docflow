"""Confluence source package.

Groups all the Confluence-related logic:

    - ``docflow.confluence.auth``: creation of the Confluence API client
      (authentication).
    - ``docflow.confluence.extraction``: low-level access to Confluence page and space
      data (listing pages, building page URLs and extracting the text of a page).
    - ``docflow.confluence.ingestion``: Orchestration of the ingestion (saving and
      processing Confluence documents).
"""
