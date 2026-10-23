import requests
import streamlit as st

from agentops.dashboard_utils import (
    format_datetime,
    format_duration,
    humanize_key,
    normalize_status,
    parse_execution_summary,
)


def navigate_to_run(run_id: str) -> None:
    """Select a related run in the Run Inspector."""
    st.session_state["selected_run_id"] = run_id


def display_execution_summary(summary, status: str) -> None:
    """Render execution summaries and highlight workflow failures."""
    normalized_status = normalize_status(status)

    if summary is None or summary == "":
        if normalized_status == "failed":
            st.error("This workflow run failed, but no failure details were recorded.")
        else:
            st.caption("No execution summary was recorded.")
        return

    parsed = parse_execution_summary(summary)

    if normalized_status == "failed":
        st.error("Workflow execution failed.")

        if parsed is not None:
            error_type = parsed.get("error_type")
            execution_error = parsed.get("execution_error")

            if error_type:
                st.markdown("**Error type**")
                st.code(str(error_type), language=None)

            if execution_error:
                st.markdown("**Failure reason**")
                st.warning(str(execution_error))
            else:
                st.caption("No specific exception message was recorded.")

            # Show useful processing context when available.
            context_fields = {
                "source_name": "Source",
                "total_orders": "Total orders",
                "processed_orders": "Orders processed before failure",
                "imported_count": "Orders imported",
                "rejected_count": "Orders rejected",
            }

            available_fields = [
                (label, parsed[key])
                for key, label in context_fields.items()
                if key in parsed
            ]

            if available_fields:
                st.markdown("**Execution context**")
                columns = st.columns(min(len(available_fields), 3))

                for index, (label, value) in enumerate(available_fields):
                    with columns[index % len(columns)]:
                        st.markdown(f"**{label}**")
                        st.write(value)

            extra_fields = {
                key: value
                for key, value in parsed.items()
                if key not in context_fields
                and key not in {"execution_error", "error_type"}
            }

            if extra_fields:
                with st.expander("Additional execution details"):
                    st.json(extra_fields)

        elif isinstance(summary, str):
            # Older runs may contain a plain-text failure summary.
            st.markdown("**Failure details**")
            st.write(summary)

        else:
            st.write(summary)

    elif parsed is None:
        if isinstance(summary, str):
            st.write(summary)
        else:
            st.write(summary)

        with st.expander("View raw execution data"):
            st.json(summary)

        return

    else:
        # Render Order Import results as operational metrics.
        order_fields = {
            "total_orders",
            "imported_count",
            "rejected_count",
        }

        if order_fields.intersection(parsed.keys()):
            metric_fields = [
                ("Orders processed", parsed.get("total_orders", 0)),
                ("Imported", parsed.get("imported_count", 0)),
                ("Rejected", parsed.get("rejected_count", 0)),
            ]

            result_columns = st.columns(3)

            for column, (label, value) in zip(result_columns, metric_fields):
                with column:
                    st.metric(label, value)

            source_name = parsed.get("source_name")

            if source_name:
                st.markdown("**Source**")
                st.code(str(source_name), language=None)

            extra_fields = {
                key: value
                for key, value in parsed.items()
                if key not in order_fields and key != "source_name"
            }

            if extra_fields:
                st.markdown("**Additional results**")

                for key, value in extra_fields.items():
                    st.markdown(f"**{humanize_key(key)}**")

                    if isinstance(value, (dict, list)):
                        st.json(value)
                    else:
                        st.write(value)

        else:
            st.markdown("**Recorded results**")

            for key, value in parsed.items():
                st.markdown(f"**{humanize_key(key)}**")

                if isinstance(value, (dict, list)):
                    st.json(value)
                else:
                    st.write(value)

    # Keep the original structured summary available for troubleshooting.
    with st.expander("View raw execution data"):
        if parsed is not None:
            st.json(parsed)
        elif isinstance(summary, str):
            st.code(summary, language=None)
        else:
            st.write(summary)


def render_retry_history(
    selected_run: dict,
    fetch_data,
) -> None:
    """Display the complete retry family using the retry-history API."""
    selected_id = selected_run["id"]

    try:
        family = fetch_data(f"/runs/{selected_id}/retry-history")
    except requests.RequestException:
        st.warning(
            "Unable to retrieve retry history. "
            "Check the API connection and try again."
        )
        return

    if not family:
        st.info("No retry history is available for this run.")
        return

    runs_by_id = {run["id"]: run for run in family}

    if selected_id not in runs_by_id:
        st.warning("The retry-history response did not include " "the selected run.")
        return

    # Find the oldest ancestor so the history starts at the original run.
    current = runs_by_id[selected_id]
    visited_ancestors = set()

    while current.get("retry_of_run_id"):
        parent_id = current["retry_of_run_id"]

        if parent_id in visited_ancestors:
            st.warning("A cycle was detected in the retry relationships.")
            break

        parent = runs_by_id.get(parent_id)

        if parent is None:
            st.warning(
                "The retry history contains a reference to a "
                "parent run that was not returned by the API."
            )
            break

        visited_ancestors.add(current["id"])
        current = parent

    root_id = current["id"]

    # Build the parent-to-children relationships.
    children_by_parent = {}

    for run in family:
        parent_id = run.get("retry_of_run_id")

        if parent_id and parent_id in runs_by_id:
            children_by_parent.setdefault(parent_id, []).append(run)

    # Traverse the family from the original run.
    history = []
    depths = {}
    queue = [(root_id, 0)]
    visited = set()

    while queue:
        run_id, depth = queue.pop(0)

        if run_id in visited:
            continue

        visited.add(run_id)
        run = runs_by_id.get(run_id)

        if run is None:
            continue

        history.append(run)
        depths[run_id] = depth

        for child in children_by_parent.get(run_id, []):
            if child["id"] not in visited:
                queue.append((child["id"], depth + 1))

    # Keep the selected run visible even if the family contains
    # malformed relationships that prevent normal traversal.
    if selected_id not in visited:
        history.append(runs_by_id[selected_id])
        depths[selected_id] = 0

    st.markdown("#### Retry History")
    st.caption(
        "Original execution and all retry descendants returned "
        "by the retry-history API."
    )

    for run in history:
        run_id = run["id"]
        depth = depths.get(run_id, 0)
        status = run.get("status", "unknown")
        normalized = normalize_status(status)
        prefix = "↳ " * depth
        is_selected = run_id == selected_id

        with st.container(border=True):
            title_col, status_col = st.columns([4, 1])

            with title_col:
                label = "Original run" if run_id == root_id else "Retry run"

                if is_selected:
                    label += " · Currently inspecting"

                st.markdown(f"**{prefix}{label}**")
                st.caption(run_id)
                st.caption(f"Created: {format_datetime(run.get('created_at'))}")

                duration = format_duration(
                    run.get("started_at"),
                    run.get("finished_at"),
                    status,
                )
                st.caption(f"Duration: {duration}")

            with status_col:
                display_status = status.replace("_", " ").title()

                if normalized == "succeeded":
                    st.success(display_status)
                elif normalized == "failed":
                    st.error(display_status)
                elif normalized == "running":
                    st.info(display_status)
                else:
                    st.write(display_status)

            if not is_selected:
                st.button(
                    "Inspect run",
                    on_click=navigate_to_run,
                    args=(run_id,),
                    key=f"history_inspect_{selected_id}_{run_id}",
                )
