
# AgentOps Project Notes

## Project Goal

Build a local-first AI Automation Control Center for managing,
executing, monitoring, and safely recovering predefined business workflows.

## Confirmed Decisions

- Workflow category: Business operations
- First workflow: Order import and validation
- Execution: Manual initially
- Frontend: Streamlit
- Backend: FastAPI
- MCP: Dedicated AgentOps MCP integration
- Database: SQLite
- Python: 3.12
- Package manager: uv
- AI model: Optional; deterministic handling first

## Architecture Principles

- Keep business logic in application services.
- Keep the interface separate from workflow execution.
- Validate all inputs.
- Record execution events and outcomes.
- Prevent duplicate order imports.
- Enforce recovery rules in application code.
- Require approval for consequential actions.
- Never claim success without recorded evidence.

## Current Environment

- Operating system: Windows
- Editor: VS Code
- Python: 3.12.4
- uv: 0.13.0
- Virtual environment: .venv

## Known Issues

- Project entry-point configuration needs verification.
- Git ignore rules need improvement.
- Application dependencies have not yet been selected or installed.

## Session Log

Record completed tasks, test results, unresolved problems,
and the next task at the end of each working session.


### 2026-10-17 — Clean project setup

- Created a separate AgentOps project.
- Initialized the project with uv and Python 3.12.4.
- Created and verified the .venv environment.
- Corrected and tested the project entry point.
- Added Git ignore rules for local secrets, databases, and caches.
- Created the project checklist and notes.
- Created the initial source and test directories.
- Verified: `uv sync` and `uv run agentops` succeeded.
- Next: finalize the SQLite schema before implementing the database.
