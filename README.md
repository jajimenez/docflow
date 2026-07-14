# Docflow

Docflow ingests documentation from multiple sources — Azure DevOps wikis, Confluence
spaces, and PDF files — into a PostgreSQL vector database and exposes the knowledge base
through an MCP (Model Context Protocol) server so AI agents can answer questions about
the documentation.

## Table of contents

- [Architecture](#architecture)
- [Development](#development)
- [Production](#production)
- [Usage](#usage)

---

## Architecture

```mermaid
graph TD
    subgraph Sources
        ADO[Azure DevOps Wikis]
        CF[Confluence Spaces]
        PDF[PDF Files]
    end

    subgraph Airflow["Apache Airflow (DAG Processor · Scheduler · API Server)"]
        DAG_ADO[ingest_azure_devops_wikis]
        DAG_CF[ingest_confluence_spaces]
        DAG_PDF[ingest_pdf_files]
    end

    subgraph Processing
        Docling[Docling — PDF text extraction]
        Markdownify[markdownify — HTML → Markdown]
        Splitter[LangChain Text Splitter — chunking]
        Ollama[Ollama — nomic-embed-text embeddings]
    end

    subgraph Storage
        KDB[(Knowledge DB\nPostgreSQL + pgvector)]
        ADB[(Airflow Metadata DB\nPostgreSQL)]
    end

    subgraph Clients
        MCP[MCP Server\nStreamable HTTP]
        AI_Agent[AI Agent]
    end

    ADO --> DAG_ADO
    CF  --> DAG_CF
    PDF --> DAG_PDF

    DAG_ADO --> Splitter
    DAG_CF  --> Markdownify --> Splitter
    DAG_PDF --> Docling    --> Splitter
    Splitter --> Ollama --> KDB

    Airflow --> ADB
    MCP --> KDB
    MCP --> Ollama
    AI_Agent --> MCP
```

### Key components

| Component | Role |
|---|---|
| **Apache Airflow 3** | Orchestrates ingestion pipelines with the DAG Processor, Scheduler and API Server running as separate processes |
| **PostgreSQL + pgvector** | Stores documents and their vector embeddings in the knowledge database |
| **Ollama (model `nomic-embed-text:v1.5`)** | Generates 768-dimensional text embeddings locally, with no external API dependency |
| **Docling** | Extracts text from PDF files using layout analysis (with Tesseract OCR as a back-end) |
| **atlassian-python-api** | Fetches pages from Confluence Cloud and Server/Data Center instances |
| **azure-devops** | Fetches pages from Azure DevOps wiki repositories |
| **markdownify** | Converts Confluence HTML page content to Markdown before chunking |
| **LangChain Text Splitters** | Splits document text into overlapping chunks for embedding |
| **MCP server (FastMCP)** | Exposes the knowledge base to AI assistants via the Model Context Protocol over Streamable HTTP |

### DAGs

#### `ingest_azure_devops_wikis`

Runs on a **daily** schedule. Ingests every Azure DevOps wiki listed in the
`docflow_azure_devops_targets` Airflow variable.

```
set_up_database
    └── get_azure_devops_targets
            └── save_documents          (mapped — one task per wiki)
                    └── flatten_documents
                            └── process_document   (mapped — one task per page)
```

Each `process_document` task fetches the wiki page text, splits it into chunks,
generates embeddings, and writes them to the knowledge database.

#### `ingest_confluence_spaces`

Runs on a **daily** schedule. Ingests every Confluence space listed in the
`docflow_confluence_targets` Airflow variable.

```
set_up_database
    └── get_confluence_targets
            └── save_documents          (mapped — one task per space)
                    └── flatten_documents
                            └── process_document   (mapped — one task per page)
```

Each `process_document` task fetches the Confluence page HTML, converts it to Markdown
with markdownify, splits it into chunks, generates embeddings, and writes them to the
knowledge database.

#### `ingest_pdf_files`

Runs on a **continuous** schedule, polling every 30 seconds.

```
set_up_database
    └── wait_for_pdf_files   (sensor — reschedule mode, 30 s interval)
            └── save_documents
                    └── process_document   (mapped — one task per file)
```

Each `process_document` task uses Docling to extract text from the PDF, splits it into
chunks, generates embeddings, and moves the file to the `processed/` or `failed/`
directory depending on the outcome.

---

## Development

### Prerequisites

- Docker — recommended with **4 CPUs and 8 GB of memory**
- Visual Studio Code with the Dev Containers extension (extension ID *ms-vscode-remote.remote-containers*)

If you are using Colima for running Docker, start it with the recommended resources:

```bash
colima start --cpu 4 --memory 8
```

### Opening the dev container

1. Clone the repository and open the folder in VS Code.
2. When prompted, click **Reopen in Container** (or run
   **Dev Containers: Reopen in Container** from the Command Palette).

VS Code builds the Docker images and runs `postCreateCommand`
(`.devcontainer/airflow-init.sh`), which:
- Installs the `docflow` package in editable mode.
- Generates `AIRFLOW__API__SECRET_KEY` and `AIRFLOW__CORE__FERNET_KEY` into
  `.devcontainer/secrets.env` if they do not already exist.
- Runs `airflow db migrate`.
- Creates the `knowledge_db` Airflow connection.
- Sets the PDF directory Airflow variables.

### Local overrides (`docker-compose.local.yml`)

`docker-compose.local.yml` (gitignored) is loaded alongside `docker-compose.yml` and
lets you override settings for your machine without touching version-controlled files.
A template is provided at `.devcontainer/docker-compose.local.example.yml`.

Common use case — Colima / remote SSH users who need `socat` to proxy the Adminer port
so VS Code port forwarding works:

```yaml
services:
  airflow:
    command: ["/bin/bash", "-c", "socat TCP-LISTEN:8081,fork,reuseaddr TCP:adminer:8080 & sleep infinity"]
```

### Running Airflow

Inside the dev container, Airflow components must be started manually in separate VS Code
terminals:

**Terminal 1 — DAG Processor:**
```bash
airflow dag-processor
```

**Terminal 2 — Scheduler:**
```bash
airflow scheduler
```

**Terminal 3 — API Server (web UI on port 8080):**
```bash
airflow api-server
```

The web UI is available at `http://localhost:8080`. The default credentials are `admin` /
`admin`.

### Running tests

```bash
pytest
```

### Corporate CA certificates

If your network uses a TLS-inspecting proxy, place your corporate root CA certificate
(PEM-encoded, `.crt` extension) in the `certificates/` directory at the repository root.
It will be installed into the Docker images at build time. This directory is gitignored.

---

## Production

### Prerequisites

- Docker — recommended with **4 CPUs and 8 GB of memory**

If you are using Colima to run Docker, start it with the recommended resources:

```bash
colima start --cpu 4 --memory 8
```

### Configuration

Copy `.env.example` to `.env` and fill in all required values:

```bash
cp .env.example .env
```

Generate the two stable cryptographic secrets and paste them into `.env`:

```bash
# AIRFLOW_SECRET_KEY — signs JWT tokens for API/UI sessions
openssl rand -base64 32

# AIRFLOW_FERNET_KEY — encrypts connection passwords and variables in the metadata DB
# Keep this value forever; changing it makes all encrypted data permanently unreadable.
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Set the host paths for the PDF pipeline directories in `.env`:

```
PDF_PENDING_DIR=/path/to/your/pdf/pending
PDF_PROCESSED_DIR=/path/to/your/pdf/processed
PDF_FAILED_DIR=/path/to/your/pdf/failed
```

### Starting the stack

```bash
docker compose up -d
```

On first start, the `airflow-init` service runs automatically. It migrates the Airflow
metadata database, writes the admin password file, registers the `knowledge_db` connection,
and sets the PDF directory variables. All steps are idempotent and run on every
`docker compose up`.

| Service | URL |
|---|---|
| Airflow web UI | `http://localhost:8080` |
| MCP server | `http://localhost:8000/mcp` |
| Adminer (DB admin) | `http://localhost:8081` |

### Stopping the stack

```bash
docker compose down          # keeps volumes (data is preserved)
docker compose down -v       # also deletes volumes (data is lost)
```

---

## Usage

### Airflow connections and variables

The required connections and variables are created automatically in the **dev container**
(by `airflow-init.sh`) and in **production** (by the `airflow-init` service). The instructions
below are for adding ingestion targets after the stack is running, via the Airflow web UI or CLI.

---

#### `ingest_pdf_files`

No connections required. Drop PDF files into the configured pending directory; the DAG
picks them up automatically.

**Variables**

| Variable | Description | Set by init |
|---|---|---|
| `docflow_pdf_pending_dir` | Absolute path to the PDF pending directory (inside the container) | ✓ |
| `docflow_pdf_processed_dir` | Absolute path to the PDF processed directory (inside the container) | ✓ |
| `docflow_pdf_failed_dir` | Absolute path to the PDF failed directory (inside the container) | ✓ |

---

#### `ingest_azure_devops_wikis`

**Connection** — create one connection per Azure DevOps organization:

| Field | Value |
|---|---|
| Connection ID | any name, e.g. `azure_devops_org` |
| Connection Type | `Generic` |
| Host | `dev.azure.com/org` (or the full URL) |
| Schema | `https` |
| Password | Personal Access Token (PAT), or leave empty for public projects |

Via CLI:
```bash
airflow connections add azure_devops_org \
  --conn-type generic \
  --conn-host "dev.azure.com/org" \
  --conn-schema https \
  --conn-password "pat"
```

**Variable** — `docflow_azure_devops_targets` (JSON array):

```json
[
  {"conn_id": "azure_devops_org_1", "project": "project-1", "wiki": "project-1.wiki"},
  {"conn_id": "azure_devops_org_2", "project": "project-2", "wiki": "project-2.wiki"}
]
```

Via CLI:
```bash
airflow variables set docflow_azure_devops_targets \
  '[{"conn_id": "azure_devops_myorg", "project": "project-1", "wiki": "project-1.wiki"}]'
```

---

#### `ingest_confluence_spaces`

**Connection** — create one connection per Confluence host/credential set:

| Field | Value |
|---|---|
| Connection ID | any name, e.g. `confluence_host` |
| Connection Type | `Generic` |
| Host | hostname, e.g. `confluence.example.com` |
| Schema | `https` |
| Login | username or email (leave empty for anonymous) |
| Password | password or API token (leave empty for anonymous) |
| Extra (JSON) | `{"token": "...", "verify_ssl": true, "cloud": false}` (all optional) |

Via CLI (username/password):
```bash
airflow connections add confluence_host \
  --conn-type generic \
  --conn-host "confluence.example.com" \
  --conn-schema https \
  --conn-login "user" \
  --conn-password "token"
```

For Confluence Cloud with a personal access token only:
```bash
airflow connections add confluence_cloud \
  --conn-type generic \
  --conn-host "org.atlassian.net" \
  --conn-schema https \
  --conn-extra '{"token":"pat", "cloud":true}'
```

**Variable** — `docflow_confluence_targets` (JSON array):

```json
[
  {"conn_id": "confluence_host_1", "space_key": "a"},
  {"conn_id": "confluence_host_2", "space_key": "b"},
  {"conn_id": "confluence_host_3", "space_key": "c"}
]
```

Via CLI:
```bash
airflow variables set docflow_confluence_targets \
  '[{"conn_id": "confluence_host", "space_key": "a"}]'
```

---

### MCP server

The MCP server exposes the knowledge base to AI assistants via the Model Context Protocol
over Streamable HTTP. It requires a Bearer token for all requests (`DOCFLOW_MCP_API_KEY`).

**Endpoint:** `http://localhost:8000/mcp`

**Tools available to the AI assistant:**

| Tool | Description |
|---|---|
| `search_documents` | Semantic similarity search over all document chunks. Primary tool for answering questions. |
| `list_documents` | Lists all successfully ingested documents. Useful for discovering what sources are available. |
| `get_document_chunks` | Returns the full ordered text of a specific document by ID. |

**Configuring VS Code Copilot** — add to your VS Code `settings.json`:

```json
{
  "mcp": {
    "servers": {
      "docflow": {
        "type": "http",
        "url": "http://localhost:8000/mcp",
        "headers": {
          "Authorization": "Bearer api-key"
        }
      }
    }
  }
}
```
