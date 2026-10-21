"""PubMed E-utilities — guidelines and reviews (standard of care)."""

from core.config import get_settings
from tools import http_client

BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
GUIDELINE_TYPES = "(practice guideline[pt] OR guideline[pt] OR consensus development conference[pt])"
REVIEW_TYPES = "(systematic review[pt] OR meta-analysis[pt])"
TREATMENT_FOCUS = "(therapy[sh] OR drug therapy[sh] OR treatment[Title] OR management[Title])"


def search_reviews(condition: str, mesh_term: str, years: int, max_results: int) -> list[dict]:
    """Guidelines first (most authoritative), then treatment-focused systematic reviews to fill up."""
    focus = f'"{http_client.clean_term(condition)}"[Title]'
    if mesh_term.strip():
        focus = f'({focus} OR "{http_client.clean_term(mesh_term)}"[MeSH Major Topic])'
    base = f'{focus} AND {TREATMENT_FOCUS} AND "last {years} years"[dp]'

    ids = _search(f"{base} AND {GUIDELINE_TYPES}", max_results)
    if len(ids) < max_results:
        ids += [i for i in _search(f"{base} AND {REVIEW_TYPES}", max_results) if i not in ids]
    ids = ids[:max_results]
    if not ids:
        return []

    summary = _get("esummary.fcgi", {"db": "pubmed", "id": ",".join(ids), "retmode": "json"}).get("result", {})
    return [
        {
            "pmid": pmid,
            "title": summary[pmid].get("title", ""),
            "journal": summary[pmid].get("source", ""),
            "pub_date": summary[pmid].get("pubdate", ""),
            "pub_types": summary[pmid].get("pubtype", []),
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        }
        for pmid in ids
        if pmid in summary
    ]


def fetch_abstracts(pmids: list[str]) -> str:
    ids = [p for p in pmids if p.isdigit()]
    if not ids:
        return ""
    response = http_client.get(f"{BASE_URL}/efetch.fcgi", _with_key({"db": "pubmed", "id": ",".join(ids), "rettype": "abstract", "retmode": "text"}))
    response.raise_for_status()
    return response.text


def _search(term: str, max_results: int) -> list[str]:
    result = _get("esearch.fcgi", {"db": "pubmed", "term": term, "retmax": max_results, "sort": "relevance", "retmode": "json"})
    return result.get("esearchresult", {}).get("idlist", [])


def _get(endpoint: str, params: dict) -> dict:
    response = http_client.get(f"{BASE_URL}/{endpoint}", _with_key(params))
    response.raise_for_status()
    return response.json()


def _with_key(params: dict) -> dict:
    api_key = get_settings().ncbi_api_key
    return {**params, "api_key": api_key} if api_key else params
