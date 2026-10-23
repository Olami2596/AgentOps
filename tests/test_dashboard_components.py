from streamlit.testing.v1 import AppTest


def run_summary_component(summary, status: str):
    """Run the real summary component in an isolated Streamlit test app."""
    app_code = f"""
from agentops.dashboard_components import display_execution_summary

display_execution_summary({summary!r}, {status!r})
"""
    return AppTest.from_string(app_code).run()


def test_successful_order_import_displays_correct_metrics():
    summary = {
        "source_name": "orders-test.csv",
        "total_orders": 10,
        "imported_count": 8,
        "rejected_count": 2,
    }

    app = run_summary_component(summary, "succeeded")

    assert not app.exception
    assert len(app.metric) == 3

    assert app.metric[0].label == "Orders processed"
    assert str(app.metric[0].value) == "10"

    assert app.metric[1].label == "Imported"
    assert str(app.metric[1].value) == "8"

    assert app.metric[2].label == "Rejected"
    assert str(app.metric[2].value) == "2"


def test_failed_execution_displays_error_details():
    summary = {
        "source_name": "orders-test.csv",
        "total_orders": 5,
        "processed_orders": 2,
        "imported_count": 1,
        "rejected_count": 1,
        "error_type": "ValidationError",
        "execution_error": "Order amount is invalid.",
    }

    app = run_summary_component(summary, "failed")

    assert not app.exception
    assert any("Workflow execution failed." in element.value for element in app.error)
    assert any(element.value == "ValidationError" for element in app.code)
    assert any("Order amount is invalid." in element.value for element in app.warning)


def test_failed_execution_without_summary_shows_fallback():
    app = run_summary_component(None, "failed")

    assert not app.exception
    assert any(
        "This workflow run failed, but no failure details were recorded."
        in element.value
        for element in app.error
    )


def test_plain_text_failure_summary_remains_readable():
    app = run_summary_component(
        "Legacy failure message",
        "failed",
    )

    assert not app.exception
    assert any("Workflow execution failed." in element.value for element in app.error)
    assert any("Failure details" in element.value for element in app.markdown)
    assert any("Legacy failure message" in element.value for element in app.markdown)


def test_generic_json_summary_displays_recorded_results():
    summary = {
        "records_checked": 12,
        "source": "inventory-service",
    }

    app = run_summary_component(summary, "succeeded")

    assert not app.exception
    assert any("Recorded results" in element.value for element in app.markdown)
    assert any("Records checked" in element.value for element in app.markdown)
    assert any("Source" in element.value for element in app.markdown)


def test_missing_successful_summary_shows_fallback():
    app = run_summary_component(None, "succeeded")

    assert not app.exception
    assert any(
        "No execution summary was recorded." in element.value for element in app.caption
    )



# ---------------------------------------------------------
# Retry history component tests
# ---------------------------------------------------------


def make_run(run_id, status, retry_of_run_id=None):
    """Create synthetic workflow run data."""
    return {
        "id": run_id,
        "status": status,
        "retry_of_run_id": retry_of_run_id,
        "created_at": "2026-10-22T10:00:00",
        "started_at": None,
        "finished_at": None,
    }


def run_retry_history_component(selected_run, fetched_runs=None):
    """Test retry history using mocked complete-family API responses."""
    if fetched_runs is None:
        fetched_runs = {}

    app_code = f"""
import requests

from agentops.dashboard_components import render_retry_history

selected_run = {selected_run!r}
fetched_runs = {fetched_runs!r}


def fake_fetch_data(endpoint):
    if endpoint.endswith("/retry-history"):
        run_id = endpoint.rsplit("/", 2)[-2]

        if run_id in fetched_runs:
            return fetched_runs[run_id]

    raise requests.RequestException("Mock API failure")


render_retry_history(
    selected_run,
    fake_fetch_data,
)
"""

    return AppTest.from_string(app_code).run()


def test_retry_history_displays_original_and_retry():
    original = make_run("run-original", "failed")
    retry = make_run("run-retry", "succeeded", "run-original")

    app = run_retry_history_component(
        selected_run=retry,
        fetched_runs={
            "run-retry": [original, retry],
        },
    )

    assert not app.exception

    captions = [element.value for element in app.caption]
    markdown = [element.value for element in app.markdown]

    assert "run-original" in captions
    assert "run-retry" in captions
    assert any("Original run" in value for value in markdown)
    assert any("Retry run" in value for value in markdown)
    assert any("Currently inspecting" in value for value in markdown)


def test_retry_history_inspect_button_navigates_to_parent():
    original = make_run("run-original", "failed")
    retry = make_run("run-retry", "succeeded", "run-original")

    app = run_retry_history_component(
        selected_run=retry,
        fetched_runs={
            "run-retry": [original, retry],
        },
    )

    assert not app.exception

    inspect_buttons = [
        button
        for button in app.button
        if button.label == "Inspect run"
    ]

    assert len(inspect_buttons) == 1

    inspect_buttons[0].click().run()

    assert not app.exception
    assert app.session_state["selected_run_id"] == "run-original"


def test_retry_history_includes_parent_outside_recent_runs():
    original = make_run("run-original", "failed")
    retry = make_run("run-retry", "succeeded", "run-original")

    # The recent-runs list contains only the selected retry.
    # The new API returns both runs in the complete family.
    app = run_retry_history_component(
        selected_run=retry,
        fetched_runs={
            "run-retry": [original, retry],
        },
    )

    assert not app.exception

    captions = [element.value for element in app.caption]

    assert "run-original" in captions
    assert "run-retry" in captions


def test_retry_history_handles_api_error():
    retry = make_run("run-retry", "succeeded", "run-missing")

    app = run_retry_history_component(
        selected_run=retry,
    )

    assert not app.exception

    assert any(
        "Unable to retrieve retry history" in element.value
        for element in app.warning
    )


def test_retry_history_detects_cycle():
    run_a = make_run("run-a", "failed", "run-b")
    run_b = make_run("run-b", "failed", "run-a")

    app = run_retry_history_component(
        selected_run=run_a,
        fetched_runs={
            "run-a": [run_a, run_b],
        },
    )

    assert not app.exception

    assert any(
        "A cycle was detected" in element.value
        for element in app.warning
    )
