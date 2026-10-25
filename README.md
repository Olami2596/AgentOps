# AgentOps — AI Automation Control Center

AgentOps is a local-first control center for registering workflows, monitoring executions, inspecting failures, and managing controlled retry operations.

## Features

- Workflow registry and execution history
- FastAPI REST API for workflow and run information
- API-key authentication with read-only and operator access levels
- Workflow health metrics and stale-run diagnostics
- Retry requests, approval tracking, and retry history
- SQLite persistence, audit events, and execution diagnostics
- Streamlit operations dashboard
- MCP server integration

## Technology Stack

- Python 3.12+
- FastAPI and Uvicorn
- Streamlit
- SQLite
- Model Context Protocol (MCP)
- `uv` for dependency and environment management
- `pytest` for automated tests

## Prerequisites

Install Python 3.12 or later and [`uv`](https://docs.astral.sh/uv/).

Run the following commands from the project root.

## Installation

Clone the repository and enter its directory. Then install the project and development dependencies:

```powershell
uv sync --dev
```

## Configuration

Create your local environment file from the example:

```powershell
Copy-Item .env.example .env
```

Generate two different random API keys. Run this command twice:

```powershell
uv run python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Copy the first output into `.env` as the value of `AGENTOPS_READ_KEY`, and the second output into `AGENTOPS_OPERATOR_KEY`.

Your `.env` should contain:

```dotenv
AGENTOPS_READ_KEY=your-generated-read-key
AGENTOPS_OPERATOR_KEY=your-different-generated-operator-key
```

Replace the example values with the generated keys. Never commit your actual `.env` file or share its secrets.

The dashboard uses the read-only key. The operator key is reserved for authorized operations.

The dashboard API URL defaults to `http://127.0.0.1:8000`. To use a different API address, configure `AGENTOPS_API_URL` in `.env`.

## Initialize the Database

AgentOps stores its SQLite database in the project root as `agentops.db`.

Initialize the schema with:

```powershell
uv run python -m agentops.database.init_db
```

Expected output:

```text
Database initialized successfully.
```

Initialization applies the schema and required compatibility checks to the existing database. Do not delete the database to perform routine initialization.

## Run the Application

Start the API and dashboard in separate PowerShell terminals, with the virtual environment activated or by using `uv run`.

### 1. Start the FastAPI backend

```powershell
uv run uvicorn agentops.api:app --host 127.0.0.1 --port 8000
```

The API is available locally at `http://127.0.0.1:8000`.

Interactive API documentation is available at `http://127.0.0.1:8000/docs`.

Protected endpoints require the `X-API-Key` header.

### 2. Start the Streamlit dashboard

In a second terminal:

```powershell
uv run streamlit run src/agentops/dashboard.py
```

Open the local URL printed by Streamlit in your browser.

The dashboard retrieves information through the FastAPI backend using the read-only API key.

## API Endpoints

| Method | Endpoint                         | Purpose                                    |
| ------ | -------------------------------- | ------------------------------------------ |
| GET    | `/workflows`                   | List registered workflows                  |
| GET    | `/workflows/health`            | Retrieve workflow health metrics           |
| GET    | `/workflows/stale-runs`        | Identify potentially stale executions      |
| GET    | `/runs`                        | List recent workflow runs                  |
| GET    | `/runs/{run_id}`               | Retrieve a workflow run                    |
| GET    | `/runs/{run_id}/retry-history` | Retrieve the retry family for a run        |
| POST   | `/runs/{run_id}/retry`         | Request a retry, requiring operator access |

Read-only endpoints accept either configured key. The retry-request endpoint requires the operator key and creates a pending approval request; it does not itself mean that the retry has executed.

## Run Tests

Run the complete test suite:

```powershell
uv run pytest -q
```

Run an individual test module, for example:

```powershell
uv run pytest tests/test_api.py -q
```

Check that the dependency lockfile is consistent:

```powershell
uv lock --check
```

## Security Notes

- Use distinct, randomly generated read and operator keys.
- Keep `.env`, database files, and local backups out of version control.
- Do not expose the operator key to the dashboard or ordinary read-only clients.
- The API and dashboard commands above bind the API to the local loopback interface. This is appropriate for local development, not a complete production deployment.
- The read-only key limits API operations but does not authenticate people who can access the Streamlit interface itself.
- Before exposing AgentOps to other users or networks, configure appropriate dashboard access controls, transport security, secret management, and deployment safeguards.

## Project Structure

```text
AgentOps/
├── src/
│   └── agentops/
│       ├── api.py
│       ├── auth.py
│       ├── dashboard.py
│       ├── dashboard_api.py
│       ├── database/
│       │   ├── connection.py
│       │   ├── init_db.py
│       │   └── schema.sql
│       └── workflows/
├── scripts/
├── tests/
├── .env.example
├── .gitignore
├── pyproject.toml
├── uv.lock
└── README.md
```

## Development Status

AgentOps is an actively developed local-first project. Features, endpoints, and deployment guidance may change as the project progresses through security hardening and release-readiness work.
