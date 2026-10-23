import requests
import streamlit as st
from agentops.dashboard_api import fetch_data
from agentops.dashboard_utils import (
    format_datetime,
    format_duration,
    normalize_status,
)
from agentops.dashboard_components import (
    display_execution_summary,
    navigate_to_run,
    render_retry_history,
)

st.set_page_config(
    page_title="AgentOps Control Center",
    page_icon="⚙️",
    layout="wide",
)

header_col, refresh_col = st.columns([5, 1])

with header_col:
    st.title("AgentOps Control Center")
    st.caption("Workflow operations and execution monitoring")

with refresh_col:
    st.write("")
    if st.button("Refresh", icon=":material/refresh:", use_container_width=True):
        st.rerun()

st.divider()

# Retrieve current workflow and run data.
try:
    workflows = fetch_data("/workflows")
    runs = fetch_data("/runs?limit=50")
except requests.RequestException:
    st.error("Unable to retrieve data. Check that the AgentOps API is running.")
    st.stop()
except RuntimeError as exc:
    st.error(str(exc))
    st.stop()

# Calculate execution counts.
status_counts = {
    "succeeded": 0,
    "failed": 0,
    "running": 0,
}

for run in runs:
    status = normalize_status(run["status"])

    if status in status_counts:
        status_counts[status] += 1

# System overview.
st.subheader("System Overview")

metric1, metric2, metric3, metric4 = st.columns(4)

with metric1:
    st.metric("Workflows", len(workflows))

with metric2:
    st.metric("Total Runs", len(runs))

with metric3:
    st.metric("Succeeded", status_counts["succeeded"])

with metric4:
    st.metric("Failed", status_counts["failed"])

st.caption(
    f'{status_counts["running"]} run(s) currently running '
    "within the recent-run window."
)

st.divider()

# Workflow registry.
st.subheader("Workflows")

if workflows:
    workflow_rows = [
        {
            "Name": workflow["name"],
            "Description": workflow["description"],
            "Status": "Enabled" if workflow["enabled"] else "Disabled",
            "Created": format_datetime(workflow["created_at"]),
        }
        for workflow in workflows
    ]

    st.dataframe(
        workflow_rows,
        width="stretch",
        hide_index=True,
    )
else:
    st.info("No workflows found.")

st.divider()

# Recent execution history.
st.subheader("Recent Workflow Runs")

if runs:
    run_rows = [
        {
            "Workflow": run["workflow_id"],
            "Run ID": run["id"],
            "Status": run["status"].replace("_", " ").title(),
            "Created": format_datetime(run["created_at"]),
        }
        for run in runs
    ]

    st.dataframe(
        run_rows,
        width="stretch",
        hide_index=True,
    )

    # Include recent runs and any referenced parent runs.
    run_ids = list(
        dict.fromkeys(
            [run["id"] for run in runs]
            + [run["retry_of_run_id"] for run in runs if run.get("retry_of_run_id")]
        )
    )

    run_labels = {
        run["id"]: (
            f'{run["workflow_id"]} | '
            f'{run["status"].replace("_", " ").title()} | '
            f'{run["id"]}'
        )
        for run in runs
    }

    # A parent run may be older than the recent-runs window.
    for run_id in run_ids:
        if run_id not in run_labels:
            run_labels[run_id] = f"Related run | {run_id}"

    st.divider()
    st.subheader("Run Inspector")
    st.caption("Select an execution to inspect its recorded details.")

    # Keep the selection valid when the list of runs changes.
    if (
        "selected_run_id" in st.session_state
        and st.session_state["selected_run_id"] not in run_ids
    ):
        del st.session_state["selected_run_id"]

    selected_run_id = st.selectbox(
        "Select a workflow run",
        options=run_ids,
        format_func=lambda run_id: run_labels[run_id],
        key="selected_run_id",
    )

    try:
        selected_run = fetch_data(f"/runs/{selected_run_id}")

        st.markdown("#### Execution Details")

        detail1, detail2, detail3 = st.columns(3)

        with detail1:
            st.markdown("**Status**")
            status = selected_run["status"].replace("_", " ").title()

            if normalize_status(selected_run["status"]) == "succeeded":
                st.success(status)
            elif normalize_status(selected_run["status"]) == "failed":
                st.error(status)
            elif normalize_status(selected_run["status"]) == "running":
                st.info(status)
            else:
                st.write(status)

        with detail2:
            st.markdown("**Workflow ID**")
            st.code(selected_run["workflow_id"], language=None)

        with detail3:
            st.markdown("**Run ID**")
            st.code(selected_run["id"], language=None)

        timing1, timing2, timing3 = st.columns(3)

        with timing1:
            st.markdown("**Started**")
            st.write(format_datetime(selected_run.get("started_at")))

        with timing2:
            st.markdown("**Finished**")
            st.write(format_datetime(selected_run.get("finished_at")))

        with timing3:
            st.markdown("**Created**")
            st.write(format_datetime(selected_run.get("created_at")))

        
        duration = format_duration(
            selected_run.get("started_at"),
            selected_run.get("finished_at"),
            selected_run.get("status", ""),
        )

        st.metric("Execution Duration", duration)


        st.divider()
        st.markdown("#### Execution Summary")
        display_execution_summary(
            selected_run.get("summary"),
            selected_run.get("status", ""),
        )

        st.divider()
        st.markdown("#### Retry Relationship")

        render_retry_history(selected_run, fetch_data)

    except requests.RequestException:
        st.error(
            "Unable to retrieve the selected run's details. "
            "Check the API connection and try again."
        )

else:
    st.info("No workflow runs found.")
