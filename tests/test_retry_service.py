import json
import pytest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from agentops.database import (
    connection,
    init_db,
    workflow_registry,
    workflow_runs,
    order_import_items,
    run_events,audit_events
)
from agentops.workflows import (
    retry_service,
    order_import,
    order_service,
)


@pytest.fixture
def test_db(tmp_path, monkeypatch):
    database_path = tmp_path / "test_agentops.db"

    monkeypatch.setattr(
        connection,
        "DATABASE_PATH",
        database_path,
    )

    temporary_connection = lambda: connection.get_connection(database_path)

    modules_to_patch = [
        init_db,
        workflow_registry,
        workflow_runs,
        order_import_items,
        run_events,
        retry_service,
        order_import,
        order_service,
    ]

    for module in modules_to_patch:
        monkeypatch.setattr(
            module,
            "get_connection",
            temporary_connection,
        )

    init_db.initialize_database()

    workflow_id = workflow_registry.register_workflow(
        "Retry Test Workflow",
        "A workflow used for retry service tests.",
    )

    return database_path, workflow_id


def create_run_with_status(workflow_id, status):
    run_id = workflow_runs.create_run(workflow_id)

    if status != "pending":
        workflow_runs.update_run_status(run_id, "running")

        if status != "running":
            workflow_runs.update_run_status(
                run_id,
                status,
                summary=f"Run finished with status {status}.",
            )

    return run_id


def valid_order(order_id="ORD-RETRY-001"):
    return {
        "external_order_id": order_id,
        "customer_reference": "CUST-RETRY-001",
        "amount": "25.50",
        "currency": "USD",
        "order_date": "2026-10-17",
    }


def save_original_order_input(run_id, order=None):
    """Give a retryable run the original payload needed for reprocessing."""
    if order is None:
        order = valid_order()

    order_import_items.save_order_import_items(
        run_id,
        "retry-test-shop",
        [order],
    )


def create_approval(database_path, run_id, status):
    from datetime import datetime, timezone
    from uuid import uuid4

    approval_id = str(uuid4())
    now = datetime.now(timezone.utc).isoformat()

    with connection.get_connection(database_path) as conn:
        conn.execute(
            """
            INSERT INTO approvals (
                id, run_id, action, status, created_at, decided_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                approval_id,
                run_id,
                "retry_workflow",
                status,
                now,
                now if status != "pending" else None,
            ),
        )

    return approval_id


def test_succeeded_run_is_not_eligible_for_retry(test_db):
    _, workflow_id = test_db
    run_id = create_run_with_status(workflow_id, "succeeded")

    result = retry_service.check_retry_eligibility(run_id)

    assert result["eligible"] is False
    assert "cannot be retried" in result["reason"]


def test_failed_run_is_eligible_for_retry(test_db):
    _, workflow_id = test_db
    run_id = create_run_with_status(workflow_id, "failed")

    result = retry_service.check_retry_eligibility(run_id)

    assert result["eligible"] is True
    assert result["reason"] == "Run status allows a retry."


def test_nonexistent_run_raises_lookup_error(test_db):
    with pytest.raises(LookupError, match="does not exist"):
        retry_service.check_retry_eligibility("missing-run")


def test_retry_request_creates_pending_approval(test_db):
    database_path, workflow_id = test_db
    run_id = create_run_with_status(workflow_id, "failed")

    approval_id = retry_service.request_retry(run_id)

    with connection.get_connection(database_path) as conn:
        approval = conn.execute(
            """
            SELECT run_id, action, status, created_at
            FROM approvals
            WHERE id = ?
            """,
            (approval_id,),
        ).fetchone()

    assert approval is not None
    assert approval["run_id"] == run_id
    assert approval["action"] == "retry_workflow"
    assert approval["status"] == "pending"
    assert approval["created_at"] is not None


@pytest.mark.parametrize("approval_status", ["pending", "rejected"])
def test_pending_or_rejected_approval_cannot_execute_retry(
    test_db,
    approval_status,
):
    database_path, workflow_id = test_db
    run_id = create_run_with_status(workflow_id, "failed")
    approval_id = create_approval(
        database_path,
        run_id,
        approval_status,
    )

    with pytest.raises(
        ValueError,
        match="approved approval record",
    ):
        retry_service.execute_approved_retry(approval_id)


def test_approved_retry_creates_and_processes_new_run(test_db):
    database_path, workflow_id = test_db
    original_run_id = create_run_with_status(workflow_id, "failed")
    save_original_order_input(original_run_id)

    approval_id = retry_service.request_retry(original_run_id)
    retry_service.decide_retry_approval(approval_id, "approved")

    retry_run_id = retry_service.execute_approved_retry(approval_id)

    retry_run = workflow_runs.get_run(retry_run_id)

    assert retry_run is not None
    assert retry_run["id"] == retry_run_id
    assert retry_run["workflow_id"] == workflow_id
    assert retry_run["status"] == "succeeded"
    assert retry_run["retry_of_run_id"] == original_run_id
    assert retry_run_id != original_run_id

    # The original run remains unchanged.
    original_run = workflow_runs.get_run(original_run_id)
    assert original_run["status"] == "failed"

    # The retry input belongs to the retry run, not the original run.
    with connection.get_connection(database_path) as conn:
        retry_items = conn.execute(
            """
            SELECT run_id, source_name, external_order_id, payload, status
            FROM order_import_items
            WHERE run_id = ?
            """,
            (retry_run_id,),
        ).fetchall()

    assert len(retry_items) == 1
    assert retry_items[0]["run_id"] == retry_run_id
    assert retry_items[0]["source_name"] == "retry-test-shop"
    assert retry_items[0]["external_order_id"] == "ORD-RETRY-001"
    assert retry_items[0]["status"] == "imported"


def test_retry_run_references_original_run(test_db):
    _, workflow_id = test_db
    original_run_id = create_run_with_status(
        workflow_id,
        "partially_succeeded",
    )
    save_original_order_input(original_run_id)

    approval_id = retry_service.request_retry(original_run_id)
    retry_service.decide_retry_approval(approval_id, "approved")

    retry_run_id = retry_service.execute_approved_retry(approval_id)

    retry_run = workflow_runs.get_run(retry_run_id)

    assert retry_run["retry_of_run_id"] == original_run_id
    assert retry_run["status"] == "succeeded"


def test_retry_without_saved_inputs_is_rejected(test_db):
    database_path, workflow_id = test_db
    original_run_id = create_run_with_status(workflow_id, "failed")

    approval_id = retry_service.request_retry(original_run_id)
    retry_service.decide_retry_approval(approval_id, "approved")

    with pytest.raises(
        ValueError,
        match="no saved order inputs",
    ):
        retry_service.execute_approved_retry(approval_id)

    # The failed attempt must not claim the approval or leave a retry run.
    with connection.get_connection(database_path) as conn:
        approval = conn.execute(
            """
            SELECT retry_run_id
            FROM approvals
            WHERE id = ?
            """,
            (approval_id,),
        ).fetchone()

        retry_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM workflow_runs
            WHERE retry_of_run_id = ?
            """,
            (original_run_id,),
        ).fetchone()[0]

    assert approval["retry_run_id"] is None
    assert retry_count == 0


def test_decided_approval_cannot_be_decided_again(test_db):
    _, workflow_id = test_db
    run_id = create_run_with_status(workflow_id, "failed")

    approval_id = retry_service.request_retry(run_id)
    retry_service.decide_retry_approval(approval_id, "approved")

    with pytest.raises(
        ValueError,
        match="Only pending approvals can be decided",
    ):
        retry_service.decide_retry_approval(approval_id, "rejected")


def test_invalid_approval_decision_is_rejected(test_db):
    _, workflow_id = test_db
    run_id = create_run_with_status(workflow_id, "failed")
    approval_id = retry_service.request_retry(run_id)

    with pytest.raises(
        ValueError,
        match="Decision must be",
    ):
        retry_service.decide_retry_approval(approval_id, "cancelled")


def test_nonexistent_approval_raises_lookup_error(test_db):
    with pytest.raises(LookupError, match="does not exist"):
        retry_service.execute_approved_retry("missing-approval")


def test_approved_retry_can_only_execute_once(test_db):
    database_path, workflow_id = test_db

    original_run_id = create_run_with_status(
        workflow_id,
        "failed",
    )
    save_original_order_input(original_run_id)

    approval_id = retry_service.request_retry(original_run_id)
    retry_service.decide_retry_approval(
        approval_id,
        "approved",
    )

    first_retry_id = retry_service.execute_approved_retry(
        approval_id,
    )

    assert first_retry_id != original_run_id

    first_retry = workflow_runs.get_run(first_retry_id)
    assert first_retry is not None
    assert first_retry["status"] == "succeeded"
    assert first_retry["retry_of_run_id"] == original_run_id

    with pytest.raises(
        ValueError,
        match="already been used",
    ):
        retry_service.execute_approved_retry(approval_id)

    with connection.get_connection(database_path) as conn:
        retry_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM workflow_runs
            WHERE retry_of_run_id = ?
            """,
            (original_run_id,),
        ).fetchone()[0]

        approval = conn.execute(
            """
            SELECT retry_run_id
            FROM approvals
            WHERE id = ?
            """,
            (approval_id,),
        ).fetchone()

    assert retry_count == 1
    assert approval["retry_run_id"] == first_retry_id


def test_retry_processing_exception_marks_run_failed_and_consumes_approval(
    test_db,
    monkeypatch,
):
    database_path, workflow_id = test_db

    original_run_id = create_run_with_status(
        workflow_id,
        "failed",
    )
    save_original_order_input(original_run_id)

    approval_id = retry_service.request_retry(original_run_id)
    retry_service.decide_retry_approval(
        approval_id,
        "approved",
    )

    def fail_processing(
        order,
        source_name,
        run_id,
        item_id=None,
    ):
        raise RuntimeError("Simulated retry processing failure")

    monkeypatch.setattr(
        order_import,
        "process_order",
        fail_processing,
    )

    with pytest.raises(
        RuntimeError,
        match="Simulated retry processing failure",
    ):
        retry_service.execute_approved_retry(approval_id)

    with connection.get_connection(database_path) as conn:
        approval = conn.execute(
            """
            SELECT status, retry_run_id
            FROM approvals
            WHERE id = ?
            """,
            (approval_id,),
        ).fetchone()

    assert approval["status"] == "approved"
    assert approval["retry_run_id"] is not None

    retry_run = workflow_runs.get_run(approval["retry_run_id"])
    assert retry_run is not None
    assert retry_run["status"] == "failed"
    assert retry_run["retry_of_run_id"] == original_run_id


def test_retry_skips_inputs_already_marked_imported(test_db):
    database_path, workflow_id = test_db

    original_run_id = create_run_with_status(workflow_id, "failed")

    orders = [
        valid_order("ORD-RETRY-IMPORTED"),
        valid_order("ORD-RETRY-PENDING"),
    ]

    item_ids = order_import_items.save_order_import_items(
        original_run_id,
        "retry-test-shop",
        orders,
    )

    order_import_items.update_order_import_item_status(
        item_ids[0],
        "imported",
    )

    approval_id = retry_service.request_retry(original_run_id)
    retry_service.decide_retry_approval(approval_id, "approved")

    retry_run_id = retry_service.execute_approved_retry(approval_id)

    with connection.get_connection(database_path) as conn:
        retry_items = conn.execute(
            """
            SELECT external_order_id, status
            FROM order_import_items
            WHERE run_id = ?
            ORDER BY rowid
            """,
            (retry_run_id,),
        ).fetchall()

    assert len(retry_items) == 1
    assert retry_items[0]["external_order_id"] == "ORD-RETRY-PENDING"
    assert retry_items[0]["status"] == "imported"


def test_retry_handles_order_imported_by_another_run(test_db):
    database_path, workflow_id = test_db

    original_run_id = create_run_with_status(workflow_id, "failed")
    order = valid_order()
    save_original_order_input(original_run_id, order)

    other_run_id = create_run_with_status(workflow_id, "running")

    order_service.process_order(
        order,
        "retry-test-shop",
        other_run_id,
    )

    approval_id = retry_service.request_retry(original_run_id)
    retry_service.decide_retry_approval(approval_id, "approved")

    retry_run_id = retry_service.execute_approved_retry(approval_id)

    retry_run = workflow_runs.get_run(retry_run_id)
    assert retry_run is not None
    assert retry_run["status"] == "failed"

    with connection.get_connection(database_path) as conn:
        order_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM orders
            WHERE source_name = ?
              AND external_order_id = ?
            """,
            ("retry-test-shop", order["external_order_id"]),
        ).fetchone()[0]

    assert order_count == 1


def test_approved_retry_is_rejected_if_workflow_is_disabled(test_db):
    database_path, workflow_id = test_db

    # Create the original failed run while the workflow is enabled.
    original_run_id = create_run_with_status(
        workflow_id,
        "failed",
    )
    save_original_order_input(original_run_id)

    # Create and approve the retry request.
    approval_id = retry_service.request_retry(original_run_id)
    retry_service.decide_retry_approval(
        approval_id,
        "approved",
    )

    # Disable the workflow after the approval has been granted.
    with connection.get_connection(database_path) as conn:
        conn.execute(
            """
            UPDATE workflows
            SET enabled = 0
            WHERE id = ?
            """,
            (workflow_id,),
        )

    # The retry must be rejected before creating a retry run
    # or consuming the approval.
    with pytest.raises(
        ValueError,
        match="disabled",
    ):
        retry_service.execute_approved_retry(approval_id)

    with connection.get_connection(database_path) as conn:
        approval = conn.execute(
            """
            SELECT status, retry_run_id
            FROM approvals
            WHERE id = ?
            """,
            (approval_id,),
        ).fetchone()

        retry_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM workflow_runs
            WHERE retry_of_run_id = ?
            """,
            (original_run_id,),
        ).fetchone()[0]

        order_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM orders
            WHERE run_id = ?
            """,
            (original_run_id,),
        ).fetchone()[0]

    assert approval["status"] == "approved"
    assert approval["retry_run_id"] is None
    assert retry_count == 0
    assert order_count == 0

def test_unexpected_retry_processing_exception_marks_run_failed(
    test_db,
    monkeypatch,
):
    database_path, workflow_id = test_db

    # 1. Create a failed original run and save retryable input.
    original_run_id = create_run_with_status(
        workflow_id,
        "failed",
    )
    save_original_order_input(original_run_id)

    # 2. Request and approve the retry.
    approval_id = retry_service.request_retry(original_run_id)
    retry_service.decide_retry_approval(
        approval_id,
        "approved",
    )

    # 3. Simulate an unexpected failure in process_orders_in_run().
    def fail_processing(orders, source_name, run_id):
        raise RuntimeError("Unexpected retry processing failure")

    monkeypatch.setattr(
        retry_service,
        "process_orders_in_run",
        fail_processing,
    )

    # 4. Verify the exception propagates.
    with pytest.raises(
        RuntimeError,
        match="Unexpected retry processing failure",
    ):
        retry_service.execute_approved_retry(approval_id)

    # 5. Retrieve the retry run ID stored on the approval.
    with retry_service.get_connection() as connection:
        approval = connection.execute(
            """
            SELECT retry_run_id
            FROM approvals
            WHERE id = ?
            """,
            (approval_id,),
        ).fetchone()

    assert approval is not None
    retry_run_id = approval["retry_run_id"]
    assert retry_run_id is not None

    # 6. Verify the retry run was not left running.
    retry_run = workflow_runs.get_run(retry_run_id)

    assert retry_run is not None
    assert retry_run["status"] == "failed"
    assert retry_run["summary"]

    summary = json.loads(retry_run["summary"])

    assert summary["execution_error"] == (
        "Unexpected retry processing failure"
    )
    assert summary["error_type"] == "RuntimeError"


def test_deciding_approval_records_audit_event(test_db):
    database_path, workflow_id = test_db

    run_id = create_run_with_status(workflow_id, "failed")
    approval_id = retry_service.request_retry(run_id)

    retry_service.decide_retry_approval(
        approval_id,
        "approved",
    )

    with connection.get_connection(database_path) as conn:
        approval = conn.execute(
            """
            SELECT status
            FROM approvals
            WHERE id = ?
            """,
            (approval_id,),
        ).fetchone()

        audit_events_for_decision = conn.execute(
            """
            SELECT actor, action, target_id, outcome, details
            FROM audit_events
            WHERE target_id = ?
            AND action = 'retry_approval_decided'
            """,
            (approval_id,),
        ).fetchall()

    assert approval is not None
    assert approval["status"] == "approved"

    assert len(audit_events_for_decision) == 1
    audit_event = audit_events_for_decision[0]
    assert audit_event["actor"] == "retry_service"
    assert audit_event["action"] == "retry_approval_decided"
    assert audit_event["target_id"] == approval_id
    assert audit_event["outcome"] == "success"
    assert json.loads(audit_event["details"]) == {
        "decision": approval["status"],
    }

def test_audit_failure_rolls_back_approval_decision(
    test_db,
    monkeypatch,
):
    database_path, workflow_id = test_db

    run_id = create_run_with_status(workflow_id, "failed")
    approval_id = retry_service.request_retry(run_id)

    def fail_audit_write(*args, **kwargs):
        raise RuntimeError("Audit write failed")

    monkeypatch.setattr(
        audit_events,
        "record_audit_event",
        fail_audit_write,
    )

    with pytest.raises(
        RuntimeError,
        match="Audit write failed",
    ):
        retry_service.decide_retry_approval(
            approval_id,
            "approved",
        )

    with connection.get_connection(database_path) as conn:
        approval = conn.execute(
            """
            SELECT status
            FROM approvals
            WHERE id = ?
            """,
            (approval_id,),
        ).fetchone()

        audit_event = conn.execute(
            """
            SELECT id
            FROM audit_events
            WHERE target_id = ?
              AND action = 'retry_approval_decided'
            """,
            (approval_id,),
        ).fetchone()

    assert approval is not None
    assert approval["status"] == "pending"
    assert audit_event is None


def test_retry_request_records_audit_event(test_db):
    database_path, workflow_id = test_db
    run_id = create_run_with_status(workflow_id, "failed")

    approval_id = retry_service.request_retry(run_id)

    with connection.get_connection(database_path) as conn:
        approval = conn.execute(
            """
            SELECT id, run_id, action, status
            FROM approvals
            WHERE id = ?
            """,
            (approval_id,),
        ).fetchone()

        audit_events_for_request = conn.execute(
            """
            SELECT actor, action, target_id, outcome, details
            FROM audit_events
            WHERE action = 'retry_approval_requested'
            AND target_id = ?
            """,
            (approval_id,),
        ).fetchall()

    assert approval is not None
    assert approval["id"] == approval_id
    assert approval["run_id"] == run_id
    assert approval["action"] == "retry_workflow"
    assert approval["status"] == "pending"

    assert len(audit_events_for_request) == 1
    audit_event = audit_events_for_request[0]
    assert audit_event["actor"] == "retry_service"
    assert audit_event["action"] == "retry_approval_requested"
    assert audit_event["target_id"] == approval_id
    assert audit_event["outcome"] == "success"
    assert json.loads(audit_event["details"]) == {"run_id": run_id}


def test_audit_failure_rolls_back_retry_request(test_db, monkeypatch):
    database_path, workflow_id = test_db
    run_id = create_run_with_status(workflow_id, "failed")

    def fail_audit_write(*args, **kwargs):
        raise RuntimeError("Audit write failed")

    monkeypatch.setattr(
        audit_events,
        "record_audit_event",
        fail_audit_write,
    )

    with pytest.raises(RuntimeError, match="Audit write failed"):
        retry_service.request_retry(run_id)

    with connection.get_connection(database_path) as conn:
        approval = conn.execute(
            """
            SELECT id
            FROM approvals
            WHERE run_id = ?
              AND action = 'retry_workflow'
            """,
            (run_id,),
        ).fetchone()

        audit_events_for_run = conn.execute(
            """
            SELECT id
            FROM audit_events
            WHERE action = 'retry_approval_requested'
              AND json_extract(details, '$.run_id') = ?
            """,
            (run_id,),
        ).fetchall()

    assert approval is None
    assert audit_events_for_run == []


def test_approved_retry_records_started_audit_event(test_db):
    database_path, workflow_id = test_db
    original_run_id = create_run_with_status(workflow_id, "failed")
    save_original_order_input(original_run_id)

    approval_id = retry_service.request_retry(original_run_id)
    retry_service.decide_retry_approval(approval_id, "approved")

    retry_run_id = retry_service.execute_approved_retry(approval_id)

    with connection.get_connection(database_path) as conn:
        start_events = conn.execute(
            """
            SELECT actor, action, target_id, outcome, details
            FROM audit_events
            WHERE action = 'retry_started'
            AND target_id = ?
            """,
            (retry_run_id,),
        ).fetchall()

    assert len(start_events) == 1
    audit_event = start_events[0]
    assert audit_event["actor"] == "retry_service"
    assert audit_event["action"] == "retry_started"
    assert audit_event["target_id"] == retry_run_id
    assert audit_event["outcome"] == "success"
    assert json.loads(audit_event["details"]) == {
        "approval_id": approval_id,
        "original_run_id": original_run_id,
    }

def test_retry_started_audit_failure_rolls_back_creation(
    test_db,
    monkeypatch,
):
    database_path, workflow_id = test_db
    original_run_id = create_run_with_status(workflow_id, "failed")
    save_original_order_input(original_run_id)

    approval_id = retry_service.request_retry(original_run_id)
    retry_service.decide_retry_approval(approval_id, "approved")

    def fail_audit_write(*args, **kwargs):
        raise RuntimeError("Audit write failed")

    monkeypatch.setattr(
        audit_events,
        "record_audit_event",
        fail_audit_write,
    )

    with pytest.raises(RuntimeError, match="Audit write failed"):
        retry_service.execute_approved_retry(approval_id)

    with connection.get_connection(database_path) as conn:
        retry_runs = conn.execute(
            """
            SELECT id
            FROM workflow_runs
            WHERE retry_of_run_id = ?
            """,
            (original_run_id,),
        ).fetchall()

        approval = conn.execute(
            """
            SELECT run_id, status, retry_run_id
            FROM approvals
            WHERE id = ?
            """,
            (approval_id,),
        ).fetchone()

        audit_events_for_run = conn.execute(
            """
            SELECT id
            FROM audit_events
            WHERE action = 'retry_started'
              AND json_extract(details, '$.original_run_id') = ?
            """,
            (original_run_id,),
        ).fetchall()

    # The retry-run insert must have rolled back.
    assert retry_runs == []

    # The original approval remains available for another attempt.
    assert approval is not None
    assert approval["run_id"] == original_run_id
    assert approval["status"] == "approved"
    assert approval["retry_run_id"] is None

    # No retry-start audit event was persisted.
    assert audit_events_for_run == []

    # The original run remains unchanged.
    original_run = workflow_runs.get_run(original_run_id)
    assert original_run is not None
    assert original_run["status"] == "failed"


def test_unexpected_retry_processing_failure_is_audited(
    test_db,
    monkeypatch,
):
    database_path, workflow_id = test_db
    original_run_id = create_run_with_status(workflow_id, "failed")
    save_original_order_input(original_run_id)

    approval_id = retry_service.request_retry(original_run_id)
    retry_service.decide_retry_approval(approval_id, "approved")

    def fail_processing(*args, **kwargs):
        raise RuntimeError("Unexpected processing failure")

    monkeypatch.setattr(
        retry_service,
        "process_orders_in_run",
        fail_processing,
    )

    with pytest.raises(
        RuntimeError,
        match="Unexpected processing failure",
    ):
        retry_service.execute_approved_retry(approval_id)

    with connection.get_connection(database_path) as conn:
        retry_run = conn.execute(
            """
            SELECT id, status, retry_of_run_id, summary
            FROM workflow_runs
            WHERE retry_of_run_id = ?
            """,
            (original_run_id,),
        ).fetchone()

        approval = conn.execute(
            """
            SELECT retry_run_id
            FROM approvals
            WHERE id = ?
            """,
            (approval_id,),
        ).fetchone()

        assert approval is not None
        assert approval["retry_run_id"] is not None

        failure_events = conn.execute(
            """
            SELECT actor, action, target_id, outcome, details
            FROM audit_events
            WHERE action = 'retry_failed'
            AND target_id = ?
            """,
            (approval["retry_run_id"],),
        ).fetchall()

    assert retry_run is not None
    assert retry_run["status"] == "failed"
    assert retry_run["retry_of_run_id"] == original_run_id

    assert retry_run["summary"] is not None
    summary = json.loads(retry_run["summary"])
    assert summary["execution_error"] == "Unexpected processing failure"
    assert summary["error_type"] == "RuntimeError"

    assert len(failure_events) == 1
    audit_event = failure_events[0]
    assert audit_event["actor"] == "retry_service"
    assert audit_event["action"] == "retry_failed"
    assert audit_event["target_id"] == approval["retry_run_id"]
    assert audit_event["outcome"] == "failure"
    assert json.loads(audit_event["details"]) == {
        "approval_id": approval_id,
        "original_run_id": original_run_id,
        "error_type": "RuntimeError",
        "error": "Unexpected processing failure",
    }


def test_retry_failure_audit_error_preserves_processing_exception(
    test_db,
    monkeypatch,
):
    database_path, workflow_id = test_db
    original_run_id = create_run_with_status(workflow_id, "failed")
    save_original_order_input(original_run_id)

    approval_id = retry_service.request_retry(original_run_id)
    retry_service.decide_retry_approval(approval_id, "approved")

    def fail_processing(*args, **kwargs):
        raise RuntimeError("Original processing error")

    monkeypatch.setattr(
        retry_service,
        "process_orders_in_run",
        fail_processing,
    )

    original_audit_writer = audit_events.record_audit_event

    def fail_retry_failed_audit(*args, **kwargs):
        if kwargs.get("action") == "retry_failed":
            raise OSError("Failure audit write failed")

        return original_audit_writer(*args, **kwargs)

    monkeypatch.setattr(
        audit_events,
        "record_audit_event",
        fail_retry_failed_audit,
    )

    with pytest.raises(
        RuntimeError,
        match="Original processing error",
    ) as exc_info:
        retry_service.execute_approved_retry(approval_id)

    # The original processing error remains the propagated exception.
    assert str(exc_info.value) == "Original processing error"

    # The audit failure is attached as a diagnostic note.
    assert any(
        "Failure audit write failed" in note
        for note in getattr(exc_info.value, "__notes__", [])
    )

    # Recovery should still have marked the retry run as failed.
    with connection.get_connection(database_path) as conn:
        retry_run = conn.execute(
            """
            SELECT id, status
            FROM workflow_runs
            WHERE retry_of_run_id = ?
            """,
            (original_run_id,),
        ).fetchone()

        approval = conn.execute(
            """
            SELECT status, retry_run_id
            FROM approvals
            WHERE id = ?
            """,
            (approval_id,),
        ).fetchone()

    assert retry_run is not None
    assert retry_run["status"] == "failed"

    # The retry had already started, so its approval remains claimed.
    assert approval["status"] == "approved"
    assert approval["retry_run_id"] == retry_run["id"]


def test_retry_recovery_failure_preserves_original_exception(
    test_db,
    monkeypatch,
):
    database_path, workflow_id = test_db
    original_run_id = create_run_with_status(workflow_id, "failed")
    save_original_order_input(original_run_id)

    approval_id = retry_service.request_retry(original_run_id)
    retry_service.decide_retry_approval(approval_id, "approved")

    def fail_processing(*args, **kwargs):
        raise RuntimeError("Original processing error")

    def fail_recovery(*args, **kwargs):
        raise OSError("Recovery update failed")

    monkeypatch.setattr(
        retry_service,
        "process_orders_in_run",
        fail_processing,
    )
    monkeypatch.setattr(
        retry_service,
        "update_run_status",
        fail_recovery,
    )

    with pytest.raises(
        RuntimeError,
        match="Original processing error",
    ) as exc_info:
        retry_service.execute_approved_retry(approval_id)

    # The processing exception must remain the propagated exception.
    assert str(exc_info.value) == "Original processing error"

    # The recovery error must be attached as a diagnostic note.
    notes = getattr(exc_info.value, "__notes__", [])
    assert any(
        "Recovery update failed" in note
        for note in notes
    )

    with connection.get_connection(database_path) as conn:
        retry_run = conn.execute(
            """
            SELECT id, status, retry_of_run_id
            FROM workflow_runs
            WHERE retry_of_run_id = ?
            """,
            (original_run_id,),
        ).fetchone()

        audit_event = conn.execute(
            """
            SELECT actor, action, target_id, outcome, details
            FROM audit_events
            WHERE action = 'retry_failed'
              AND target_id = ?
            """,
            (retry_run["id"],),
        ).fetchone()

    assert retry_run is not None
    assert retry_run["retry_of_run_id"] == original_run_id

    # Recovery was mocked to fail before changing the stored status.
    assert retry_run["status"] == "running"

    # Failure auditing should still succeed.
    assert audit_event is not None
    assert audit_event["actor"] == "retry_service"
    assert audit_event["action"] == "retry_failed"
    assert audit_event["target_id"] == retry_run["id"]
    assert audit_event["outcome"] == "failure"

    details = json.loads(audit_event["details"])
    assert details["approval_id"] == approval_id
    assert details["original_run_id"] == original_run_id
    assert details["error_type"] == "RuntimeError"
    assert details["error"] == "Original processing error"


def test_retry_with_invalid_saved_order_structure_marks_run_failed(
    test_db,
):
    database_path, workflow_id = test_db

    original_run_id = create_run_with_status(workflow_id, "failed")
    save_original_order_input(original_run_id)

    # "null" is valid JSON, but it does not represent an order dictionary.
    with connection.get_connection(database_path) as conn:
        conn.execute(
            """
            UPDATE order_import_items
            SET payload = ?
            WHERE run_id = ?
            """,
            ("null", original_run_id),
        )

    approval_id = retry_service.request_retry(original_run_id)
    retry_service.decide_retry_approval(approval_id, "approved")

    with pytest.raises(
        ValueError,
        match="Order at index 0 must be a dictionary",
    ):
        retry_service.execute_approved_retry(approval_id)

    with connection.get_connection(database_path) as conn:
        approval = conn.execute(
            """
            SELECT retry_run_id
            FROM approvals
            WHERE id = ?
            """,
            (approval_id,),
        ).fetchone()

        retry_runs = conn.execute(
            """
            SELECT id, status
            FROM workflow_runs
            WHERE retry_of_run_id = ?
            """,
            (original_run_id,),
        ).fetchall()

    assert approval is not None
    assert approval["retry_run_id"] is not None

    assert len(retry_runs) == 1
    retry_run_id = retry_runs[0]["id"]

    assert retry_run_id == approval["retry_run_id"]
    assert retry_runs[0]["status"] == "failed"

    with connection.get_connection(database_path) as conn:
        retry_items = conn.execute(
            """
            SELECT id
            FROM order_import_items
            WHERE run_id = ?
            """,
            (retry_run_id,),
        ).fetchall()

        retry_orders = conn.execute(
            """
            SELECT id
            FROM orders
            WHERE run_id = ?
            """,
            (retry_run_id,),
        ).fetchall()

        failure_event = conn.execute(
            """
            SELECT action, outcome, details
            FROM audit_events
            WHERE action = 'retry_failed'
              AND target_id = ?
            """,
            (retry_run_id,),
        ).fetchone()

    assert retry_items == []
    assert retry_orders == []

    assert failure_event is not None
    assert failure_event["outcome"] == "failure"

    details = json.loads(failure_event["details"])
    assert details["approval_id"] == approval_id
    assert details["original_run_id"] == original_run_id
    assert details["error_type"] == "ValueError"


def test_retry_with_invalid_saved_json_creates_no_retry_run(
    test_db,
):
    database_path, workflow_id = test_db

    # 1. Create an eligible original run and save an order input.
    original_run_id = create_run_with_status(
        workflow_id,
        "failed",
    )
    save_original_order_input(original_run_id)

    # 2. Corrupt the saved payload so it is not valid JSON.
    with connection.get_connection(database_path) as conn:
        conn.execute(
            """
            UPDATE order_import_items
            SET payload = ?
            WHERE run_id = ?
            """,
            ("{invalid json", original_run_id),
        )

    # 3. Request and approve the retry.
    approval_id = retry_service.request_retry(original_run_id)
    retry_service.decide_retry_approval(
        approval_id,
        "approved",
    )

    # 4. Invalid JSON must fail before a retry run is created.
    with pytest.raises(json.JSONDecodeError):
        retry_service.execute_approved_retry(approval_id)

    # 5. Verify that the approval remains available and unclaimed.
    with connection.get_connection(database_path) as conn:
        approval = conn.execute(
            """
            SELECT status, retry_run_id
            FROM approvals
            WHERE id = ?
            """,
            (approval_id,),
        ).fetchone()

        retry_runs = conn.execute(
            """
            SELECT id, status
            FROM workflow_runs
            WHERE retry_of_run_id = ?
            """,
            (original_run_id,),
        ).fetchall()

        retry_started_events = conn.execute(
            """
            SELECT id
            FROM audit_events
            WHERE action = 'retry_started'
              AND json_extract(details, '$.original_run_id') = ?
            """,
            (original_run_id,),
        ).fetchall()

    assert approval is not None
    assert approval["status"] == "approved"
    assert approval["retry_run_id"] is None

    # No retry run or retry-start audit event should exist.
    assert retry_runs == []
    assert retry_started_events == []

    # The original run must remain unchanged.
    original_run = workflow_runs.get_run(original_run_id)
    assert original_run is not None
    assert original_run["status"] == "failed"


def test_concurrent_retry_execution_creates_only_one_retry_run(
    test_db,
):
    database_path, workflow_id = test_db

    # 1. Create a failed original run and save a valid input.
    original_run_id = create_run_with_status(
        workflow_id,
        "failed",
    )
    save_original_order_input(original_run_id)

    # 2. Request and approve one retry.
    approval_id = retry_service.request_retry(original_run_id)
    retry_service.decide_retry_approval(
        approval_id,
        "approved",
    )

    # Both workers must reach the barrier before either attempts execution.
    barrier = Barrier(2)

    def attempt_retry():
        barrier.wait(timeout=10)

        try:
            retry_run_id = retry_service.execute_approved_retry(
                approval_id,
            )
            return {
                "outcome": "success",
                "retry_run_id": retry_run_id,
                "error": None,
            }
        except ValueError as exc:
            return {
                "outcome": "rejected",
                "retry_run_id": None,
                "error": str(exc),
            }

    # Each service call opens its own database connections.
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(attempt_retry),
            executor.submit(attempt_retry),
        ]
        outcomes = [future.result(timeout=30) for future in futures]

    # 3. Exactly one worker must succeed and the other must be rejected.
    successful = [
        outcome
        for outcome in outcomes
        if outcome["outcome"] == "success"
    ]
    rejected = [
        outcome
        for outcome in outcomes
        if outcome["outcome"] == "rejected"
    ]

    assert len(successful) == 1
    assert len(rejected) == 1
    assert "already been used" in rejected[0]["error"]

    retry_run_id = successful[0]["retry_run_id"]
    assert retry_run_id is not None

    # 4. Verify that exactly one retry run references the original run.
    with connection.get_connection(database_path) as conn:
        retry_runs = conn.execute(
            """
            SELECT id, status, retry_of_run_id
            FROM workflow_runs
            WHERE retry_of_run_id = ?
            """,
            (original_run_id,),
        ).fetchall()

        approval = conn.execute(
            """
            SELECT status, retry_run_id
            FROM approvals
            WHERE id = ?
            """,
            (approval_id,),
        ).fetchone()

    assert len(retry_runs) == 1
    assert retry_runs[0]["id"] == retry_run_id
    assert retry_runs[0]["retry_of_run_id"] == original_run_id

    # 5. The approval must point to the single created retry run.
    assert approval is not None
    assert approval["status"] == "approved"
    assert approval["retry_run_id"] == retry_run_id

    # 6. The retry run must not remain running.
    assert retry_runs[0]["status"] in {
        "succeeded",
        "partially_succeeded",
        "failed",
        "cancelled",
    }


def test_concurrent_approval_decisions_only_one_succeeds(test_db):
    database_path, workflow_id = test_db

    # 1. Create a failed run and a pending retry approval.
    run_id = create_run_with_status(workflow_id, "failed")
    approval_id = retry_service.request_retry(run_id)

    barrier = Barrier(2)

    # 2. Each worker waits until both threads are ready, then decides.
    def attempt_decision(decision):
        barrier.wait(timeout=10)

        try:
            retry_service.decide_retry_approval(
                approval_id,
                decision,
            )
            return {
                "decision": decision,
                "outcome": "success",
                "error": None,
            }
        except ValueError as exc:
            return {
                "decision": decision,
                "outcome": "rejected",
                "error": str(exc),
            }

    # 3. Race the approval and rejection decisions.
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(attempt_decision, "approved"),
            executor.submit(attempt_decision, "rejected"),
        ]
        outcomes = [
            future.result(timeout=30)
            for future in futures
        ]

    successful = [
        outcome
        for outcome in outcomes
        if outcome["outcome"] == "success"
    ]
    rejected = [
        outcome
        for outcome in outcomes
        if outcome["outcome"] == "rejected"
    ]

    # 4. Exactly one decision must win.
    assert len(successful) == 1
    assert len(rejected) == 1
    assert "pending" in rejected[0]["error"].lower()

    # 5. Inspect the final approval and its decision audit events.
    with connection.get_connection(database_path) as conn:
        approval = conn.execute(
            """
            SELECT status, decided_at
            FROM approvals
            WHERE id = ?
            """,
            (approval_id,),
        ).fetchone()

        audit_events_for_decision = conn.execute(
            """
            SELECT actor, action, target_id, outcome, details
            FROM audit_events
            WHERE action = 'retry_approval_decided'
              AND target_id = ?
            """,
            (approval_id,),
        ).fetchall()

    assert approval is not None
    assert approval["status"] in {"approved", "rejected"}
    assert approval["decided_at"] is not None

    # 6. Only the winning decision should have been audited.
    assert len(audit_events_for_decision) == 1

    audit_event = audit_events_for_decision[0]
    assert audit_event["actor"] == "retry_service"
    assert audit_event["action"] == "retry_approval_decided"
    assert audit_event["target_id"] == approval_id
    assert audit_event["outcome"] == "success"

    audit_details = json.loads(audit_event["details"])
    assert audit_details["decision"] == approval["status"]
