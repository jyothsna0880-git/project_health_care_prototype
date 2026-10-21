"""openFDA drug labels — FDA-approved drugs for an indication (standard of care)."""

import re
from urllib.parse import quote

from tools import http_client

BASE_URL = "https://api.fda.gov/drug/label.json"
EXCERPT_CHARS = 500
LABELS_TO_SCAN = 100  # many labels are generics of the same drug, so scan wide then dedupe


def search_approved_drugs(condition: str, max_results: int) -> list[dict]:
    params = {"search": f'indications_and_usage:"{http_client.clean_term(condition)}"', "limit": LABELS_TO_SCAN}
    response = http_client.get(BASE_URL, params)
    if response.status_code == 404:  # openFDA returns 404 for "no matches"
        return []
    response.raise_for_status()

    drugs: dict[str, dict] = {}
    for label in response.json().get("results", []):
        openfda = label.get("openfda", {})
        generic = ", ".join(openfda.get("generic_name", [])).upper()
        if not generic or generic in drugs:
            continue
        drugs[generic] = {
            "generic_name": generic,
            "brand_names": openfda.get("brand_name", []),
            "pharm_class": openfda.get("pharm_class_epc", []),
            "indication_excerpt": _excerpt(" ".join(label.get("indications_and_usage", [])), condition),
            "url": f"https://dailymed.nlm.nih.gov/dailymed/search.cfm?query={quote(generic)}",
        }
    return list(drugs.values())[:max_results]


def _excerpt(text: str, condition: str) -> str:
    """The part of the indication text that mentions the condition; labels often list several
    indications, so the first characters may not be the relevant ones."""
    words = http_client.clean_term(condition).replace("-", " ").split()
    match = re.search(r"[\s\-–]+".join(map(re.escape, words)), text, re.IGNORECASE) if words else None
    start = max(0, match.start() - EXCERPT_CHARS // 2) if match else 0
    return text[start:start + EXCERPT_CHARS]
