import json
from datetime import datetime, timezone


def format_datetime(value: str | None) -> str:
    """Format ISO timestamps for display."""
    if not value:
        return "—"

    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return timestamp.strftime("%d %b %Y, %H:%M")
    except (ValueError, TypeError):
        return str(value)


def parse_timestamp(value: str | None) -> datetime | None:
    """Parse an ISO timestamp and normalize it to UTC."""
    if not value:
        return None

    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))

        # Treat legacy timestamps without timezone information as UTC.
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)

        return timestamp.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError):
        return None


def normalize_status(status: str) -> str:
    """Normalize status values before counting them."""
    return status.strip().lower().replace(" ", "_")


def format_duration(
    started_at: str | None,
    finished_at: str | None,
    status: str,
) -> str:
    """Calculate elapsed execution time for completed or running runs."""
    started = parse_timestamp(started_at)

    if started is None:
        return "Unavailable"

    finished = parse_timestamp(finished_at)

    if finished is None:
        if normalize_status(status) != "running":
            return "Unavailable"

        finished = datetime.now(timezone.utc)

    elapsed_seconds = (finished - started).total_seconds()

    if elapsed_seconds < 0:
        return "Unavailable"

    total_seconds = int(elapsed_seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    if hours:
        return f"{hours}h {minutes}m {seconds}s"

    if minutes:
        return f"{minutes}m {seconds}s"

    return f"{seconds}s"


def humanize_key(key: str) -> str:
    """Convert machine-readable field names into readable labels."""
    return key.replace("_", " ").strip().capitalize()


def parse_execution_summary(summary):
    """Parse a JSON summary when possible without losing the original value."""
    if isinstance(summary, dict):
        return summary

    if isinstance(summary, str):
        try:
            parsed = json.loads(summary)
        except (json.JSONDecodeError, TypeError):
            return None

        if isinstance(parsed, dict):
            return parsed

    return None
