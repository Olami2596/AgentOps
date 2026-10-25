import pytest
from fastapi import HTTPException

from agentops.auth import get_access_level


def test_operator_key_grants_operator_access(monkeypatch):
    monkeypatch.setenv("AGENTOPS_READ_KEY", "read-secret")
    monkeypatch.setenv("AGENTOPS_OPERATOR_KEY", "operator-secret")

    assert get_access_level("operator-secret") == "operator"


def test_read_key_grants_read_access(monkeypatch):
    monkeypatch.setenv("AGENTOPS_READ_KEY", "read-secret")
    monkeypatch.setenv("AGENTOPS_OPERATOR_KEY", "operator-secret")

    assert get_access_level("read-secret") == "read"


def test_missing_key_is_rejected(monkeypatch):
    monkeypatch.setenv("AGENTOPS_READ_KEY", "read-secret")
    monkeypatch.setenv("AGENTOPS_OPERATOR_KEY", "operator-secret")

    with pytest.raises(HTTPException) as exc_info:
        get_access_level(None)

    assert exc_info.value.status_code == 401


def test_missing_auth_configuration_fails_closed(monkeypatch):
    monkeypatch.delenv("AGENTOPS_READ_KEY", raising=False)
    monkeypatch.delenv("AGENTOPS_OPERATOR_KEY", raising=False)

    with pytest.raises(HTTPException) as exc_info:
        get_access_level("some-key")

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == ("API authentication is not configured")


def test_identical_configured_keys_fail_closed(monkeypatch):
    monkeypatch.setenv("AGENTOPS_READ_KEY", "same-secret")
    monkeypatch.setenv("AGENTOPS_OPERATOR_KEY", "same-secret")

    with pytest.raises(HTTPException) as exc_info:
        get_access_level("same-secret")

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == ("API authentication is not configured")

def test_missing_read_key_fails_closed(monkeypatch):
    monkeypatch.delenv("AGENTOPS_READ_KEY", raising=False)
    monkeypatch.setenv("AGENTOPS_OPERATOR_KEY", "operator-secret")

    with pytest.raises(HTTPException) as exc_info:
        get_access_level("operator-secret")

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "API authentication is not configured"


def test_missing_operator_key_fails_closed(monkeypatch):
    monkeypatch.setenv("AGENTOPS_READ_KEY", "read-secret")
    monkeypatch.delenv("AGENTOPS_OPERATOR_KEY", raising=False)

    with pytest.raises(HTTPException) as exc_info:
        get_access_level("read-secret")

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "API authentication is not configured"