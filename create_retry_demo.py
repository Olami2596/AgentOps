from datetime import date
from uuid import uuid4

from agentops.database import (
    init_db,
    order_import_items,
    workflow_registry,
    workflow_runs,
)
from agentops.workflows import retry_service


def main() -> None:
    # Make sure the local database schema exists.
    init_db.initialize_database()

    # Find an enabled Order Import workflow.
    workflows = workflow_registry.list_workflows()

    workflow = next(
        (
            item
            for item in workflows
            if "order import" in item["name"].lower() and item["enabled"]
        ),
        None,
    )

    if workflow is None:
        raise RuntimeError(
            "No enabled Order Import workflow was found. "
            "Check your workflow registry before continuing."
        )

    demo_id = uuid4().hex[:8].upper()
    source_name = f"agentops-retry-demo-{demo_id}"

    order = {
        "external_order_id": f"AGENTOPS-DEMO-{demo_id}",
        "customer_reference": f"CUST-DEMO-{demo_id}",
        "amount": "25.50",
        "currency": "USD",
        "order_date": date.today().isoformat(),
    }

    # Create an original run and mark it as failed.
    original_run_id = workflow_runs.create_run(workflow["id"])

    workflow_runs.update_run_status(
        original_run_id,
        "running",
    )

    workflow_runs.update_run_status(
        original_run_id,
        "failed",
        summary="Demo failure created to test retry navigation.",
    )

    # Save the synthetic input required by the retry service.
    order_import_items.save_order_import_items(
        original_run_id,
        source_name,
        [order],
    )

    # Request approval, approve it, and execute the retry.
    approval_id = retry_service.request_retry(original_run_id)

    retry_service.decide_retry_approval(
        approval_id,
        "approved",
    )

    retry_run_id = retry_service.execute_approved_retry(
        approval_id,
    )

    # Verify the persisted parent-child relationship.
    retry_run = workflow_runs.get_run(retry_run_id)

    if retry_run is None:
        raise RuntimeError("The retry run could not be retrieved.")

    if retry_run["retry_of_run_id"] != original_run_id:
        raise RuntimeError("The retry run does not reference its original run.")

    print("\nRetry demonstration created successfully.")
    print(f"Workflow:       {workflow['name']}")
    print(f"Original run:   {original_run_id}")
    print(f"Original status: failed")
    print(f"Approval ID:    {approval_id}")
    print(f"Retry run:      {retry_run_id}")
    print(f"Retry status:   {retry_run['status']}")
    print(f"Retry parent:   {retry_run['retry_of_run_id']}")


if __name__ == "__main__":
    main()
