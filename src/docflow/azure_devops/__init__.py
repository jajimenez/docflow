"""Azure DevOps source package.

Groups all the Azure DevOps Wiki-related logic:

    - ``docflow.azure_devops.auth``: Authentication through the Azure DevOps Wiki API
      client.
    - ``docflow.azure_devops.extraction``: Low-level access to Azure DevOps wiki pages
      (listing pages, building page URLs and extracting the text of a page).
    - ``docflow.azure_devops.ingestion``: Orchestration of the ingestion (saving and
      processing Azure DevOps wiki documents).
"""
