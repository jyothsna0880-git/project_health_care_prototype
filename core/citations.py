"""Citation verification: the guard against invented sources.

Every ID the LLM cites must match a record actually retrieved from PubMed,
ClinicalTrials.gov or openFDA in this run; anything else is dropped.
"""

import re

from core.schemas import Reference

NCT_PATTERN = re.compile(r"NCT\d{8}", re.IGNORECASE)
PMID_PATTERN = re.compile(r"^(?:PMID[:\s]*)?(\d{5,9})$", re.IGNORECASE)
PMID_IN_TEXT = re.compile(r"PMID[:\s]*(\d{5,9})", re.IGNORECASE)
FDA_IN_TEXT = re.compile(r"\[(FDA:[^\[\]]+)\]", re.IGNORECASE)  # FDA names may contain commas, so only bracketed


def normalize_id(raw: str) -> str:
    raw = raw.strip()
    if match := NCT_PATTERN.search(raw):
        return match.group(0).upper()
    if match := PMID_PATTERN.match(raw):
        return f"PMID:{match.group(1)}"
    if raw.upper().startswith("FDA:"):
        return "FDA:" + raw[4:].strip().upper()
    return raw


def verify(ids: list[str], sources: dict[str, Reference]) -> tuple[list[str], list[str]]:
    """Split cited IDs into (verified, unverified), normalized and de-duplicated."""
    verified, unverified = [], []
    for raw in ids:
        normalized = normalize_id(raw)
        (verified if normalized in sources else unverified).append(normalized)
    return list(dict.fromkeys(verified)), unverified


def ids_in_text(text: str) -> list[str]:
    nct_ids = [m.upper() for m in NCT_PATTERN.findall(text)]
    pmids = [f"PMID:{m}" for m in PMID_IN_TEXT.findall(text)]
    fda_ids = [normalize_id(m) for m in FDA_IN_TEXT.findall(text)]
    return list(dict.fromkeys(nct_ids + pmids + fda_ids))
