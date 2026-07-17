# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

## [0.1.0] - 2026-07-17

### Added

- Airflow DAG `ingest_azure_devops_wikis` to ingest pages from Azure DevOps wiki repositories on a daily schedule.
- Airflow DAG `ingest_confluence_spaces` to ingest pages from Confluence spaces on a daily schedule.
- Airflow DAG `ingest_pdf_files` to ingest PDF files on a continuous schedule, polling every 30 seconds.
- PDF text extraction using Docling (with Tesseract OCR as a back-end).
- HTML-to-Markdown conversion for Confluence pages using markdownify.
- Document chunking using LangChain Text Splitters with configurable chunk size and overlap.
- Vector embedding generation using Ollama (`nomic-embed-text:v1.5`, 768 dimensions).
- PostgreSQL + pgvector knowledge database with document and chunk storage.
- MCP server (FastMCP) exposing `search_documents`, `list_documents`, and `get_document_chunks` tools over Streamable HTTP.
- Bearer token authentication for the MCP server.
- Dev container configuration for local development with VS Code.
- Production Docker Compose stack with `airflow-init` service for automated first-run setup.

[Unreleased]: https://github.com/jajimenez/docflow/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/jajimenez/docflow/releases/tag/v0.1.0
