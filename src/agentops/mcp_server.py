from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from agentops.database.workflow_registry import (
    list_workflows as list_workflows_service,
)
from agentops.database.workflow_runs import get_run as get_run_service
from agentops.workflows.retry_service import (
    check_retry_eligibility as check_retry_eligibility_service,
    request_retry as request_retry_service,
)

mcp = MCPServer("AgentOps")

@mcp.tool()
def list_workflows() -> list[dict]:
    """List enabled AgentOps workflows, ordered by name."""
    return list_workflows_service()

@mcp.tool()
def get_workflow_run(run_id: str) -> dict | None:
    """Retrieve a workflow run by ID, returning None if it doesn't exist."""
    return get_run_service(run_id)


@mcp.tool()
def check_retry_eligibility(run_id: str) -> dict:
    """Check whether a workflow run is eligible for retry."""
    try:
        return check_retry_eligibility_service(run_id)
    except LookupError as exc:
        raise ToolError(str(exc)) from exc

@mcp.tool()
def request_retry(run_id: str) -> dict:
    """Request a workflow retry by creating a pending approval.
    This tool does not execute the retry.
    """
    try:
        approval_id = request_retry_service(run_id)
    except LookupError as exc:
        raise ToolError(str(exc)) from exc
    except ValueError as exc:
        raise ToolError(str(exc)) from exc

    return {
        "approval_id": approval_id,
        "status": "pending",
        "message": "Retry approval request created successfully.",
    }


if __name__ == "__main__":
    mcp.run()
