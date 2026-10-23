import os

import requests
from dotenv import load_dotenv

load_dotenv()

API_BASE_URL = os.getenv(
    "AGENTOPS_API_URL",
    "http://127.0.0.1:8000",
)


def fetch_data(endpoint: str):
    """Fetch data from the AgentOps API using the read-only API key."""
    api_key = os.getenv("AGENTOPS_READ_KEY")

    if not api_key:
        raise RuntimeError("Read-only API key is not configured.")

    response = requests.get(
        f"{API_BASE_URL}{endpoint}",
        headers={"X-API-Key": api_key},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()
