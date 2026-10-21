"""Shared HTTP GET with a timeout and a small retry for rate limits / transient errors."""

import time

import httpx

from core.config import get_settings

RETRY_STATUSES = {429, 500, 502, 503, 504}
ATTEMPTS = 3


def get(url: str, params: dict) -> httpx.Response:
    timeout = get_settings().http_timeout
    for attempt in range(ATTEMPTS - 1):
        try:
            response = httpx.get(url, params=params, timeout=timeout)
            if response.status_code not in RETRY_STATUSES:
                return response
        except httpx.TransportError:
            pass
        time.sleep(1 + attempt)
    return httpx.get(url, params=params, timeout=timeout)


def clean_term(text: str) -> str:
    """Strip characters that break the search syntax of PubMed / openFDA / ClinicalTrials.gov."""
    return " ".join(text.replace('"', " ").replace("[", " ").replace("]", " ").split())
