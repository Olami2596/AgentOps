import pytest
from agentops.workflows.order_validation import validate_order


def valid_order():
    return {
        "external_order_id": "ORD-001",
        "customer_reference": "CUST-001",
        "amount": "25.50",
        "currency": "USD",
        "order_date": "2026-10-17",
    }


def test_valid_order_has_no_errors():
    assert validate_order(valid_order()) == []


def test_missing_required_field_is_reported():
    order = valid_order()
    del order["customer_reference"]

    errors = validate_order(order)

    assert "Missing required field: customer_reference" in errors


def test_negative_amount_is_rejected():
    order = valid_order()
    order["amount"] = "-10"

    errors = validate_order(order)

    assert "amount must be a finite, non-negative number" in errors


def test_invalid_currency_is_rejected():
    order = valid_order()
    order["currency"] = "US dollars"

    errors = validate_order(order)

    assert "currency must be a three-letter code" in errors


def test_invalid_date_is_rejected():
    order = valid_order()
    order["order_date"] = "not-a-date"

    errors = validate_order(order)

    assert "order_date must be a valid ISO date (YYYY-MM-DD)" in errors


def test_blank_order_id_is_rejected():
    order = valid_order()
    order["external_order_id"] = "   "

    errors = validate_order(order)

    assert "external_order_id must be a non-empty string" in errors





@pytest.mark.parametrize(
    "order",
    [
        None,
        [],
        "not an order",
    ],
)
def test_validate_order_rejects_non_dictionary_inputs(order):
    errors = validate_order(order)

    assert errors == ["Order must be a dictionary."]


def test_validate_order_accepts_valid_order():
    order = {
        "external_order_id": "ORD-001",
        "customer_reference": "CUST-001",
        "amount": "125.50",
        "currency": "USD",
        "order_date": "2026-10-19",
    }

    assert validate_order(order) == []
