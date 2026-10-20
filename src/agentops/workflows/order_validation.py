from datetime import date
from decimal import Decimal, InvalidOperation
import re
from typing import Any

REQUIRED_FIELDS = {
    "external_order_id",
    "customer_reference",
    "amount",
    "currency",
    "order_date",
}


def validate_order(order: Any) -> list[str]:
    errors = []

    # Reject malformed inputs before accessing dictionary methods.
    if not isinstance(order, dict):
        return ["Order must be a dictionary."]

    missing_fields = REQUIRED_FIELDS - order.keys()

    for field in sorted(missing_fields):
        errors.append(f"Missing required field: {field}")

    if missing_fields:
        return errors

    if (
        not isinstance(order["external_order_id"], str)
        or not order["external_order_id"].strip()
    ):
        errors.append("external_order_id must be a non-empty string")

    if (
        not isinstance(order["customer_reference"], str)
        or not order["customer_reference"].strip()
    ):
        errors.append("customer_reference must be a non-empty string")

    try:
        amount = Decimal(str(order["amount"]))
        if not amount.is_finite() or amount < 0:
            errors.append("amount must be a finite, non-negative number")
    except (InvalidOperation, ValueError, TypeError):
        errors.append("amount must be a valid number")

    currency = order["currency"]
    if not isinstance(currency, str) or not re.fullmatch(r"[A-Za-z]{3}", currency):
        errors.append("currency must be a three-letter code")

    try:
        if not isinstance(order["order_date"], str):
            raise ValueError
        date.fromisoformat(order["order_date"])
    except (ValueError, TypeError):
        errors.append("order_date must be a valid ISO date (YYYY-MM-DD)")

    return errors
