import re
from datetime import datetime, timedelta, timezone

import pytest

from agentops.dashboard_utils import (
    format_datetime,
    format_duration,
    humanize_key,
    normalize_status,
    parse_execution_summary,
    parse_timestamp,
)

# --------------------------------------------------
# Timestamp formatting
# --------------------------------------------------


def test_format_datetime_formats_valid_timestamp():
    result = format_datetime("2026-10-22T10:00:00Z")

    assert result == "22 Oct 2026, 10:00"


def test_format_datetime_returns_dash_for_missing_value():
    assert format_datetime(None) == "—"
    assert format_datetime("") == "—"


def test_format_datetime_returns_original_value_for_invalid_timestamp():
    result = format_datetime("not-a-valid-timestamp")

    assert result == "not-a-valid-timestamp"


# --------------------------------------------------
# Timestamp parsing
# --------------------------------------------------


def test_parse_timestamp_normalizes_utc_timestamp():
    result = parse_timestamp("2026-10-22T10:00:00Z")

    assert result == datetime(2026, 10, 22, 10, 0, tzinfo=timezone.utc)


def test_parse_timestamp_converts_timezone_to_utc():
    result = parse_timestamp("2026-10-22T12:00:00+02:00")

    assert result == datetime(2026, 10, 22, 10, 0, tzinfo=timezone.utc)


def test_parse_timestamp_treats_naive_timestamp_as_utc():
    result = parse_timestamp("2026-10-22T10:00:00")

    assert result == datetime(2026, 10, 22, 10, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("value", [None, "", "invalid-timestamp"])
def test_parse_timestamp_returns_none_for_invalid_input(value):
    assert parse_timestamp(value) is None


# --------------------------------------------------
# Status normalization
# --------------------------------------------------


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("Succeeded", "succeeded"),
        ("FAILED", "failed"),
        ("Partially Succeeded", "partially_succeeded"),
        ("running", "running"),
        ("  Cancelled  ", "cancelled"),
    ],
)
def test_normalize_status(status, expected):
    assert normalize_status(status) == expected


# --------------------------------------------------
# Execution duration
# --------------------------------------------------


def test_format_duration_for_completed_run():
    result = format_duration(
        "2026-10-22T10:00:00Z",
        "2026-10-22T10:00:05Z",
        "succeeded",
    )

    assert result == "5s"


def test_format_duration_for_minutes_and_seconds():
    result = format_duration(
        "2026-10-22T10:00:00Z",
        "2026-10-22T10:02:05Z",
        "succeeded",
    )

    assert result == "2m 5s"


def test_format_duration_for_hours_minutes_and_seconds():
    result = format_duration(
        "2026-10-22T10:00:00Z",
        "2026-10-22T11:02:03Z",
        "succeeded",
    )

    assert result == "1h 2m 3s"


def test_format_duration_for_zero_seconds():
    result = format_duration(
        "2026-10-22T10:00:00Z",
        "2026-10-22T10:00:00Z",
        "succeeded",
    )

    assert result == "0s"


def test_format_duration_for_running_run():
    started_at = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()

    result = format_duration(started_at, None, "running")

    assert re.fullmatch(r"\d+s", result)
    assert result != "Unavailable"


def test_format_duration_returns_unavailable_when_start_is_missing():
    assert format_duration(None, None, "running") == "Unavailable"


def test_format_duration_returns_unavailable_when_finished_time_is_missing():
    assert (
        format_duration(
            "2026-10-22T10:00:00Z",
            None,
            "failed",
        )
        == "Unavailable"
    )


def test_format_duration_returns_unavailable_for_negative_duration():
    result = format_duration(
        "2026-10-22T10:00:10Z",
        "2026-10-22T10:00:00Z",
        "succeeded",
    )

    assert result == "Unavailable"


def test_format_duration_handles_different_timezones():
    result = format_duration(
        "2026-10-22T12:00:00+02:00",
        "2026-10-22T10:00:05Z",
        "succeeded",
    )

    assert result == "5s"


# --------------------------------------------------
# Human-readable field names
# --------------------------------------------------


def test_humanize_key_converts_underscores_to_spaces():
    assert humanize_key("total_orders") == "Total orders"


def test_humanize_key_handles_whitespace():
    assert humanize_key("  imported_count  ") == "Imported count"


# --------------------------------------------------
# Execution summary parsing
# --------------------------------------------------


def test_parse_execution_summary_parses_valid_json():
    result = parse_execution_summary('{"total_orders": 1, "imported_count": 1}')

    assert result == {
        "total_orders": 1,
        "imported_count": 1,
    }


def test_parse_execution_summary_accepts_existing_dictionary():
    summary = {"total_orders": 3, "rejected_count": 1}

    result = parse_execution_summary(summary)

    assert result is summary


def test_parse_execution_summary_returns_none_for_malformed_json():
    assert parse_execution_summary('{"total_orders":') is None


@pytest.mark.parametrize(
    "summary",
    [
        None,
        "",
        "plain-text summary",
        "[1, 2, 3]",
        "null",
        "123",
    ],
)
def test_parse_execution_summary_returns_none_for_non_object_input(summary):
    assert parse_execution_summary(summary) is None
