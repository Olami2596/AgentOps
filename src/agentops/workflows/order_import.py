import json
from typing import Any

from agentops.database.connection import get_connection
from agentops.database.order_import_items import save_order_import_items
from agentops.database.workflow_runs import create_run, update_run_status
from agentops.workflows.order_service import process_order

MAX_SOURCE_NAME_LENGTH = 100
MAX_ORDERS_PER_IMPORT = 500
MAX_ORDER_PAYLOAD_BYTES = 64 * 1024


def _safe_order_count(orders: Any) -> int:
    """Return an order count without masking an input-validation error."""
    return len(orders) if isinstance(orders, list) else 0


def _validate_import_inputs(
    orders: list[dict[str, Any]],
    source_name: str,
) -> None:
    """Validate order-import inputs before persistence or processing."""
    if not isinstance(source_name, str):
        raise ValueError("Source name must be a string.")

    if not source_name.strip():
        raise ValueError("Source name cannot be empty or whitespace-only.")

    if len(source_name) > MAX_SOURCE_NAME_LENGTH:
        raise ValueError(
            f"Source name cannot exceed {MAX_SOURCE_NAME_LENGTH} characters."
        )

    if not isinstance(orders, list):
        raise ValueError("Orders must be provided as a list.")

    if not orders:
        raise ValueError("Cannot execute an order import with an empty order list.")

    if len(orders) > MAX_ORDERS_PER_IMPORT:
        raise ValueError(
            f"An import cannot contain more than {MAX_ORDERS_PER_IMPORT} orders."
        )

    for index, order in enumerate(orders):
        if not isinstance(order, dict):
            raise ValueError(f"Order at index {index} must be a dictionary.")

        try:
            serialized_order = json.dumps(order, ensure_ascii=False)
            payload_size = len(serialized_order.encode("utf-8"))
        except (TypeError, ValueError, UnicodeEncodeError) as exc:
            raise ValueError(
                f"Order at index {index} must be JSON-serializable."
            ) from exc

        if payload_size > MAX_ORDER_PAYLOAD_BYTES:
            raise ValueError(
                f"Order at index {index} exceeds the maximum "
                f"payload size of {MAX_ORDER_PAYLOAD_BYTES} bytes."
            )


def process_orders_in_run(
    orders: list[dict[str, Any]],
    source_name: str,
    run_id: str,
) -> dict[str, Any]:
    results = []
    imported_count = 0
    rejected_count = 0

    try:
        # Validate before saving inputs. This also protects direct retry calls.
        _validate_import_inputs(orders, source_name)

        # Save all original inputs before processing begins.
        item_ids = save_order_import_items(
            run_id,
            source_name,
            orders,
        )

        for order, item_id in zip(orders, item_ids):
            result = process_order(
                order,
                source_name,
                run_id,
                item_id=item_id,
            )
            results.append(result)

            if result["status"] == "imported":
                imported_count += 1
            elif result["status"] == "rejected":
                rejected_count += 1
            else:
                raise ValueError(
                    f"Unexpected order processing status: {result['status']!r}."
                )

    except Exception as exc:
        failure_summary = json.dumps(
            {
                "source_name": source_name,
                "total_orders": _safe_order_count(orders),
                "processed_orders": len(results),
                "imported_count": imported_count,
                "rejected_count": rejected_count,
                "execution_error": str(exc),
                "error_type": type(exc).__name__,
            }
        )

        try:
            update_run_status(
                run_id,
                "failed",
                summary=failure_summary,
            )
        except Exception as finalization_error:
            exc.add_note(
                "Additionally, the workflow run could not be marked "
                f"as failed: {finalization_error!r}"
            )

        # Preserve and propagate the original processing exception.
        raise

    if rejected_count == 0:
        final_status = "succeeded"
    elif imported_count > 0:
        final_status = "partially_succeeded"
    else:
        final_status = "failed"

    summary_data = {
        "source_name": source_name,
        "total_orders": len(orders),
        "imported_count": imported_count,
        "rejected_count": rejected_count,
    }
    summary = json.dumps(summary_data)

    # If normal finalization fails, attempt to mark the run failed.
    # Never replace the original finalization exception.
    try:
        update_run_status(
            run_id,
            final_status,
            summary=summary,
        )
    except Exception as exc:
        failure_summary = json.dumps(
            {
                "source_name": source_name,
                "total_orders": _safe_order_count(orders),
                "processed_orders": len(results),
                "imported_count": imported_count,
                "rejected_count": rejected_count,
                "execution_error": str(exc),
                "error_type": type(exc).__name__,
            }
        )

        try:
            update_run_status(
                run_id,
                "failed",
                summary=failure_summary,
            )
        except Exception as finalization_error:
            exc.add_note(
                "Additionally, the workflow run could not be marked "
                f"as failed: {finalization_error!r}"
            )

        raise

    return {
        "run_id": run_id,
        "status": final_status,
        "imported_count": imported_count,
        "rejected_count": rejected_count,
        "results": results,
        "summary": summary_data,
    }


def execute_order_import(
    orders: list[dict[str, Any]],
    source_name: str,
    workflow_id: str,
) -> dict[str, Any]:
    # Reject invalid requests before creating a run.
    _validate_import_inputs(orders, source_name)

    with get_connection() as connection:
        workflow = connection.execute(
            "SELECT id, enabled FROM workflows WHERE id = ?",
            (workflow_id,),
        ).fetchone()

    if workflow is None:
        raise LookupError(f"Workflow {workflow_id!r} does not exist.")

    if not workflow["enabled"]:
        raise ValueError(
            f"Workflow {workflow_id!r} is disabled and cannot be executed."
        )

    # create_run() also checks that the workflow remains enabled.
    run_id = create_run(workflow_id)
    update_run_status(run_id, "running")

    return process_orders_in_run(
        orders,
        source_name,
        run_id,
    )
