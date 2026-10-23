
import pytest
import requests

from agentops import dashboard_api


def test_fetch_data_returns_json_response(monkeypatch):
    """A successful request returns the API's JSON data."""
    expected_data = [
        {"id": "run-123", "status": "succeeded"}
    ]
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return expected_data

    def fake_get(url, headers, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setenv("AGENTOPS_READ_KEY", "test-read-key")
    monkeypatch.setattr(dashboard_api.requests, "get", fake_get)

    result = dashboard_api.fetch_data("/runs")

    assert result == expected_data
    assert captured["url"] == f"{dashboard_api.API_BASE_URL}/runs"
    assert captured["headers"] == {"X-API-Key": "test-read-key"}
    assert captured["timeout"] == 10


def test_fetch_data_raises_when_api_key_is_missing(monkeypatch):
    """Requests must not be made without a read-only API key."""
    monkeypatch.delenv("AGENTOPS_READ_KEY", raising=False)

    def unexpected_get(*args, **kwargs):
        pytest.fail("HTTP request should not be made without an API key")

    monkeypatch.setattr(dashboard_api.requests, "get", unexpected_get)

    with pytest.raises(
        RuntimeError,
        match="Read-only API key is not configured.",
    ):
        dashboard_api.fetch_data("/runs")


def test_fetch_data_propagates_http_error(monkeypatch):
    """HTTP errors should be raised to the calling dashboard component."""
    class FakeResponse:
        def raise_for_status(self):
            raise requests.HTTPError("401 Unauthorized")

    def fake_get(url, headers, timeout):
        return FakeResponse()

    monkeypatch.setenv("AGENTOPS_READ_KEY", "test-read-key")
    monkeypatch.setattr(dashboard_api.requests, "get", fake_get)

    with pytest.raises(requests.HTTPError, match="401 Unauthorized"):
        dashboard_api.fetch_data("/runs")


def test_fetch_data_propagates_connection_error(monkeypatch):
    """Connection failures should not be silently swallowed."""
    def fake_get(url, headers, timeout):
        raise requests.ConnectionError("API is unavailable")

    monkeypatch.setenv("AGENTOPS_READ_KEY", "test-read-key")
    monkeypatch.setattr(dashboard_api.requests, "get", fake_get)

    with pytest.raises(
        requests.ConnectionError,
        match="API is unavailable",
    ):
        dashboard_api.fetch_data("/runs")


def test_fetch_data_uses_configured_api_url(monkeypatch):
    """The request should use the configured API base URL."""
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"workflows": []}

    def fake_get(url, headers, timeout):
        captured["url"] = url
        return FakeResponse()

    monkeypatch.setenv("AGENTOPS_READ_KEY", "test-read-key")
    monkeypatch.setattr(
        dashboard_api,
        "API_BASE_URL",
        "http://test-api:8000",
    )
    monkeypatch.setattr(dashboard_api.requests, "get", fake_get)

    result = dashboard_api.fetch_data("/workflows")

    assert result == {"workflows": []}
    assert captured["url"] == "http://test-api:8000/workflows"
