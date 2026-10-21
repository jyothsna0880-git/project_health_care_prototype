"""MCP server exposing the medical research tools over stdio.

Run standalone with:  python -m tools.server
"""

import logging
from collections.abc import Callable

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from tools import clinical_trials, openfda, pubmed

logging.getLogger("httpx").setLevel(logging.WARNING)

server = MCPServer(
    "medical-research",
    instructions="Tools for researching standard of care and emerging treatments for a medical condition.",
)


def _expected_failures[T](fn: Callable[[], T]) -> T:
    """Report bad arguments and upstream API failures to the client with a readable message
    (unexpected exceptions are hidden by MCP and logged as crashes)."""
    try:
        return fn()
    except httpx.HTTPStatusError as exc:
        raise ToolError(f"{exc.request.url.host} returned HTTP {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        raise ToolError(f"network error: {type(exc).__name__}") from exc
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


@server.tool()
def search_guidelines_and_reviews(condition: str, mesh_term: str = "", years: int = 5, max_results: int = 8) -> dict:
    """Search PubMed for recent clinical practice guidelines (first) and treatment-focused systematic
    reviews / meta-analyses on a condition. Use this to establish the current standard of care."""
    return {"articles": _expected_failures(lambda: pubmed.search_reviews(condition, mesh_term, years, max_results))}


@server.tool()
def get_pubmed_abstracts(pmids: list[str]) -> str:
    """Fetch the abstracts (plain text) for up to 5 PubMed IDs."""
    return _expected_failures(lambda: pubmed.fetch_abstracts(pmids[:5]))


@server.tool()
def search_approved_drugs(condition: str, max_results: int = 20) -> dict:
    """Search openFDA drug labels for FDA-approved drugs whose indication mentions the condition."""
    return {"drugs": _expected_failures(lambda: openfda.search_approved_drugs(condition, max_results))}


@server.tool()
def search_clinical_trials(condition: str, phases: list[str] | None = None, max_results: int = 30) -> dict:
    """Search ClinicalTrials.gov for active interventional trials (recruiting or ongoing).
    `phases` uses EARLY_PHASE1, PHASE1, PHASE2, PHASE3, PHASE4 (default: PHASE2 and PHASE3)."""
    phases = phases or ["PHASE2", "PHASE3"]
    return {"trials": _expected_failures(lambda: clinical_trials.search_trials(condition, phases, max_results))}


if __name__ == "__main__":
    server.run("stdio")
