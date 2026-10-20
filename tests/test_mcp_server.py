import sqlite3
import pytest
import asyncio
from unittest.mock import patch

from agentops.mcp_server import mcp
from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError


def test_request_retry_tool_is_registered():
    tools = asyncio.run(mcp.list_tools())

    assert any(tool.name == "request_retry" for tool in tools)


def test_request_retry_returns_pending_approval():
    with patch(
        "agentops.mcp_server.request_retry_service",
        return_value="approval-test-123",
    ):
        result = asyncio.run(
            mcp.call_tool(
                "request_retry",
                {"run_id": "run-test"},
            )
        )

    assert result.is_error is False

    response_text = result.content[0].text

    assert "approval-test-123" in response_text
    assert '"pending"' in response_text
    assert "approval request created successfully" in response_text


def test_request_retry_handles_missing_workflow_run():
    with patch(
        "agentops.mcp_server.request_retry_service",
        side_effect=LookupError("Workflow run 'missing-run' does not exist."),
    ):
        try:
            asyncio.run(
                mcp.call_tool(
                    "request_retry",
                    {"run_id": "missing-run"},
                )
            )
        except ToolError as exc:
            assert "Workflow run 'missing-run' does not exist." in str(exc)
        else:
            raise AssertionError("Expected ToolError was not raised")


def test_request_retry_handles_ineligible_workflow_run():
    with patch(
        "agentops.mcp_server.request_retry_service",
        side_effect=ValueError(
            "Workflow run 'completed-run' is not eligible for retry."
        ),
    ):
        try:
            asyncio.run(
                mcp.call_tool(
                    "request_retry",
                    {"run_id": "completed-run"},
                )
            )
        except ToolError as exc:
            assert "Workflow run 'completed-run' is not eligible for retry." in str(exc)
        else:
            raise AssertionError("Expected ToolError was not raised")


def test_request_retry_does_not_swallow_database_errors():
    with patch(
        "agentops.mcp_server.request_retry_service",
        side_effect=sqlite3.OperationalError("database is locked"),
    ):
        with pytest.raises(UnexpectedToolError) as exc_info:
            asyncio.run(
                mcp.call_tool(
                    "request_retry",
                    {"run_id": "run-test"},
                )
            )

    assert "database is locked" not in str(exc_info.value)


def test_check_retry_eligibility_returns_service_result():
    with patch(
        "agentops.mcp_server.check_retry_eligibility_service",
        return_value={
            "eligible": True,
            "reason": "Run failed.",
        },
    ):
        result = asyncio.run(
            mcp.call_tool(
                "check_retry_eligibility",
                {"run_id": "run-test"},
            )
        )

    assert result.is_error is False

    response_text = result.content[0].text

    assert '"eligible": true' in response_text
    assert '"reason": "Run failed."' in response_text


def test_get_workflow_run_returns_service_result():
    with patch(
        "agentops.mcp_server.get_run_service",
        return_value={
            "id": "run-test",
            "status": "failed",
        },
    ):
        result = asyncio.run(
            mcp.call_tool(
                "get_workflow_run",
                {"run_id": "run-test"},
            )
        )

    assert result.is_error is False

    response_text = result.content[0].text

    assert "run-test" in response_text
    assert "failed" in response_text



def test_list_workflows_returns_service_result():
    with patch(
        "agentops.mcp_server.list_workflows_service",
        return_value=[
            {"id": "workflow-a", "name": "Order Import"},
            {"id": "workflow-b", "name": "Customer Feedback"},
        ],
    ):
        result = asyncio.run(
            mcp.call_tool("list_workflows", {})
        )

    assert result.is_error is False

    workflows = result.structured_content["result"]

    assert len(workflows) == 2
    assert workflows[0]["id"] == "workflow-a"
    assert workflows[0]["name"] == "Order Import"
    assert workflows[1]["id"] == "workflow-b"
    assert workflows[1]["name"] == "Customer Feedback"
