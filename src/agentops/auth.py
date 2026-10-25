import os
import secrets
from typing import Annotated, Literal

from dotenv import load_dotenv
from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader

load_dotenv()

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

AccessLevel = Literal["read", "operator"]


def get_access_level(
    api_key: Annotated[str | None, Security(api_key_header)],
) -> AccessLevel:
    read_key = os.getenv("AGENTOPS_READ_KEY")
    operator_key = os.getenv("AGENTOPS_OPERATOR_KEY")

    if not read_key or not operator_key:
        raise HTTPException(
            status_code=500,
            detail="API authentication is not configured",
        )

    if secrets.compare_digest(read_key, operator_key):
        raise HTTPException(
            status_code=500,
            detail="API authentication is not configured",
        )

    if api_key and secrets.compare_digest(api_key, operator_key):
        return "operator"

    if api_key and secrets.compare_digest(api_key, read_key):
        return "read"

    raise HTTPException(
        status_code=401,
        detail="Invalid or missing API key",
        headers={"WWW-Authenticate": "ApiKey"},
    )
