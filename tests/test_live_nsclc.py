"""Live integration: non-small cell lung cancer through the real MCP server and public APIs.

Only OpenAI is stubbed (no key needed). The stub cites real IDs taken from the evidence it is
given, plus invented ones, to prove the deterministic checks keep the first and drop the second.
Run with:  pytest -m live -s
"""

import asyncio
import json
import re
from contextlib import asynccontextmanager

import httpx
import pytest
from mcp import Client

from conftest import NSCLC
from core import briefing
from core.briefing import generate_briefing
from core.schemas import (
    CareTreatment, ConditionProfile, EmergingCandidate, EmergingDraft, ExecutiveSummary, LandscapeSummary, StandardOfCare,
)
from retrieval import mcp_client
from retrieval.mcp_client import ToolError
from tools.clinical_trials import ACTIVE_STATUSES

pytestmark = pytest.mark.live
REGISTRY = "https://clinicaltrials.gov/api/v2/studies"


def call(tool: str, args: dict, timeout: float | None = None):
    """Call one tool through the real MCP server. Errors are returned from inside the
    connection (exceptions leaving it are wrapped in ExceptionGroups by anyio) and re-raised."""
    async def go():
        async with Client(mcp_client.SERVER_PARAMS, read_timeout_seconds=timeout or 90) as client:
            toolbox = mcp_client.Toolbox(client)
            try:
                return await toolbox.call_json(tool, args)
            except ToolError as exc:
                return exc
    result = asyncio.run(go())
    if isinstance(result, ToolError):
        raise result
    return result


@pytest.fixture(scope="module")
def nsclc_trials() -> list[dict]:
    return call("search_clinical_trials", {"condition": NSCLC.standard_name, "phases": ["PHASE2", "PHASE3"], "max_results": 30})["trials"]


def test_trial_ids_and_status_match_the_registry_record(nsclc_trials):
    """Each retrieved trial is re-fetched by NCT ID and compared field by field."""
    assert len(nsclc_trials) >= 10, "expected active Phase 2/3 NSCLC trials"
    ids = [t["nct_id"] for t in nsclc_trials]
    assert all(re.fullmatch(r"NCT\d{8}", i) for i in ids) and len(set(ids)) == len(ids)
    # independent lookup by ID (not by condition search) in one request
    response = httpx.get(REGISTRY, params={"filter.ids": ",".join(ids), "pageSize": len(ids)}, timeout=30)
    response.raise_for_status()
    records = {s["protocolSection"]["identificationModule"]["nctId"]: s["protocolSection"] for s in response.json()["studies"]}
    assert set(records) == set(ids), f"IDs missing from registry: {set(ids) - set(records)}"

    mismatches = []
    for t in nsclc_trials:
        record = records[t["nct_id"]]
        registry = {
            "nct_id": record["identificationModule"]["nctId"],
            "title": record["identificationModule"]["briefTitle"],
            "status": record["statusModule"]["overallStatus"],
            "phases": record["designModule"].get("phases", []),
            "sponsor": record["sponsorCollaboratorsModule"]["leadSponsor"]["name"],
        }
        retrieved = {k: t[k] for k in registry}
        if retrieved != registry:
            mismatches.append((t["nct_id"], retrieved, registry))
        assert t["status"] in ACTIVE_STATUSES.split(","), f"{t['nct_id']} is not active: {t['status']}"
        assert {"PHASE2", "PHASE3"} & set(t["phases"]), f"{t['nct_id']} is not Phase 2/3: {t['phases']}"
        assert t["url"] == f"https://clinicaltrials.gov/study/{t['nct_id']}"
    assert not mismatches, mismatches
    print(f"\n{len(nsclc_trials)} NSCLC trials verified against registry records")


def test_pubmed_and_fda_records_exist():
    articles = call("search_guidelines_and_reviews", {"condition": NSCLC.standard_name, "mesh_term": NSCLC.mesh_term})["articles"]
    assert articles, "expected NSCLC guidelines/reviews"
    summary = httpx.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
                        params={"db": "pubmed", "id": ",".join(a["pmid"] for a in articles), "retmode": "json"}, timeout=30).json()["result"]
    for a in articles:
        assert summary[a["pmid"]]["title"] == a["title"]
    print("\nPubMed:", *(f"  {a['pmid']} {a['pub_types'][:2]} {a['title'][:80]}" for a in articles), sep="\n")

    drugs = call("search_approved_drugs", {"condition": NSCLC.standard_name})["drugs"]
    assert drugs, "expected FDA labels mentioning NSCLC"
    for d in drugs:
        assert "lung" in d["indication_excerpt"].lower(), d["generic_name"]
    print("openFDA:", ", ".join(d["generic_name"] for d in drugs))


def test_empty_results_are_empty_not_errors():
    nonsense = "zzqvx qqrrt syndrome"
    assert call("search_clinical_trials", {"condition": nonsense})["trials"] == []
    assert call("search_approved_drugs", {"condition": nonsense})["drugs"] == []
    assert call("search_guidelines_and_reviews", {"condition": nonsense})["articles"] == []


def test_bad_arguments_and_timeouts_raise_tool_error():
    with pytest.raises(ToolError, match="Invalid phases"):
        call("search_clinical_trials", {"condition": "x", "phases": ["PHASE9"]})
    with pytest.raises(ToolError, match="timed out"):
        call("search_clinical_trials", {"condition": NSCLC.standard_name, "max_results": 100}, timeout=0.01)


class EvidenceDrivenLLM:
    """Stub that cites real IDs found in its evidence plus invented ones."""

    async def structured(self, system, user, schema):
        pmids = re.findall(r'"pmid": "(\d+)"', user)
        ncts = list(dict.fromkeys(re.findall(r'"nct_id": "(NCT\d{8})"', user)))
        fdas = re.findall(r'"generic_name": "([^"]+)"', user)
        if schema is ConditionProfile:
            return NSCLC
        if schema is StandardOfCare:
            return StandardOfCare(summary="soc", treatments=[
                CareTreatment(name=fdas[0].title(), category="Named drug", role="Per label", description="d", citations=[f"FDA:{fdas[0]}", pmids[0]]),
                CareTreatment(name="Invented regimen", category="Named drug", role="First-line", description="d", citations=["PMID:99999999"]),
                CareTreatment(name="Trial-only agent", category="Named drug", role="First-line", description="d", citations=[ncts[0]] if ncts else []),
            ])
        if schema is EmergingDraft:
            return EmergingDraft(summary="pipe", treatments=[
                EmergingCandidate(name="Candidate A", mechanism=None, potential_impact="p", trial_ids=ncts[:2]),
                EmergingCandidate(name="Pembrolizumab + novel agent", mechanism=None, potential_impact="p", trial_ids=ncts[2:3]),
                EmergingCandidate(name="Ghost", mechanism=None, potential_impact="p", trial_ids=["NCT00000000"]),
            ])
        if schema is LandscapeSummary:
            return LandscapeSummary(summary="landscape")
        if schema is ExecutiveSummary:
            real = re.findall(r"NCT\d{8}", user)[0]
            return ExecutiveSummary(summary="exec", key_points=[f"Real [{real}]", "Fake [PMID:22222222]", "No source"], evidence_gaps=[])
        raise AssertionError(schema)


def test_full_pipeline_nsclc_with_real_sources(monkeypatch, no_env_file):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(briefing, "LLMClient", lambda *args: EvidenceDrivenLLM())

    b = asyncio.run(generate_briefing("NSCLC"))

    assert b.source_failures == [], b.source_failures
    trial_ids = {t.nct_id for t in b.emerging.trials}
    # every reference resolves to a record retrieved in this run
    for r in b.references:
        if r.source == "ClinicalTrials.gov":
            assert r.id in trial_ids
    # established care never cites trials; emerging cites only retrieved trials
    assert [t.name for t in b.standard_of_care.treatments] and all(
        not c.startswith("NCT") for t in b.standard_of_care.treatments for c in t.citations)
    assert all(set(t.trial_ids) <= trial_ids for t in b.emerging.treatments)
    assert [t.name for t in b.emerging.treatments][:1] == ["Candidate A"]
    # an approved agent in a new combination is flagged exactly when openFDA returned its label
    fda_names = [d["generic_name"] for d in call("search_approved_drugs", {"condition": NSCLC.standard_name})["drugs"]]
    combo = b.emerging.treatments[-1]
    assert combo.name == "Pembrolizumab + novel agent"
    assert combo.fda_labelled_agents == (["PEMBROLIZUMAB"] if any(n.startswith("PEMBROLIZUMAB") for n in fda_names) else [])
    # invented content removed
    content = json.dumps(b.model_dump(exclude={"warnings"}))
    for invented in ["99999999", "NCT00000000", "22222222", "Invented regimen", "Trial-only agent", "Ghost", "No source"]:
        assert invented not in content, invented
    assert b.landscape.organizations
    print(f"\nBriefing: {len(b.emerging.trials)} trials, {len(b.references)} references, "
          f"{len(b.landscape.organizations)} organizations, {len(b.warnings)} data-quality notes")
    for w in b.warnings:
        print("  -", w)
