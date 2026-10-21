"""Research functions: deterministic validation around the LLM drafts, empty results and source failures."""

import asyncio

from conftest import NSCLC, FakeLLM, FakeToolbox, article, drug, trial
from core.schemas import CareTreatment, EmergingCandidate, EmergingDraft, EmergingTreatment, LandscapeSummary, StandardOfCare
from research import emerging, organizations, standard_of_care
from retrieval.mcp_client import ToolError


def run(coro):
    return asyncio.run(coro)


def no_progress(_: str) -> None:
    pass


# ---------- standard of care ----------

def soc_toolbox(**overrides) -> FakeToolbox:
    responses = {
        "search_guidelines_and_reviews": {"articles": [article("11111111"), article("22222222")]},
        "get_pubmed_abstracts": "abstract text",
        "search_approved_drugs": {"drugs": [drug("OSIMERTINIB MESYLATE")]},
    }
    return FakeToolbox({**responses, **overrides})


def test_standard_of_care_keeps_only_verified_citations_and_never_trial_ids():
    draft = StandardOfCare(summary="s", treatments=[
        CareTreatment(name="EGFR TKI", category="Drug class", role="First-line", description="d", citations=["PMID:11111111", "FDA:OSIMERTINIB MESYLATE"]),
        CareTreatment(name="Invented drug", category="Named drug", role="First-line", description="d", citations=["PMID:99999999"]),
        CareTreatment(name="Trial agent", category="Named drug", role="First-line", description="d", citations=["NCT01234567"]),
        CareTreatment(name="Mixed", category="Drug class", role="Add-on", description="d", citations=["22222222", "PMID:88888888"]),
    ])
    result = run(standard_of_care.research(NSCLC, soc_toolbox(), FakeLLM({StandardOfCare: draft}), no_progress))

    kept = {t.name: t.citations for t in result.section.treatments}
    assert kept == {"EGFR TKI": ["PMID:11111111", "FDA:OSIMERTINIB MESYLATE"], "Mixed": ["PMID:22222222"]}
    assert any("Invented drug" in w for w in result.warnings)
    assert any("Trial agent" in w for w in result.warnings)  # standard of care cannot cite trials
    assert result.failures == []


def test_standard_of_care_empty_results_skip_llm():
    toolbox = soc_toolbox(search_guidelines_and_reviews={"articles": []}, search_approved_drugs={"drugs": []})
    llm = FakeLLM({})
    result = run(standard_of_care.research(NSCLC, toolbox, llm, no_progress))
    assert llm.calls == []  # nothing to synthesize from, so the model is never asked
    assert result.section.treatments == []
    assert result.failures == []
    assert "No guidelines" in result.warnings[0]


def test_standard_of_care_one_source_failing_still_uses_the_other():
    toolbox = soc_toolbox(search_guidelines_and_reviews=ToolError("search_guidelines_and_reviews failed: HTTP 503"))
    draft = StandardOfCare(summary="s", treatments=[
        CareTreatment(name="Osimertinib", category="Named drug", role="First-line", description="d", citations=["FDA:OSIMERTINIB MESYLATE"]),
    ])
    result = run(standard_of_care.research(NSCLC, toolbox, FakeLLM({StandardOfCare: draft}), no_progress))
    assert result.failures == ["search_guidelines_and_reviews failed: HTTP 503"]
    assert [t.name for t in result.section.treatments] == ["Osimertinib"]


def test_standard_of_care_all_sources_failing_reports_failure_not_empty():
    toolbox = soc_toolbox(
        search_guidelines_and_reviews=ToolError("pubmed timed out"),
        search_approved_drugs=ToolError("openfda timed out"),
    )
    llm = FakeLLM({})
    result = run(standard_of_care.research(NSCLC, toolbox, llm, no_progress))
    assert llm.calls == []
    assert result.failures == ["pubmed timed out", "openfda timed out"]
    assert result.warnings == []  # a failure must not be reported as "nothing found"


# ---------- emerging treatments ----------

def test_emerging_drops_invented_trials_and_derives_facts_from_registry():
    trials = [
        trial("NCT00000001", phases=["PHASE2"], sponsor="Acme Oncology"),
        trial("NCT00000002", phases=["PHASE2", "PHASE3"], sponsor="University Hospital", sponsor_class="OTHER"),
    ]
    draft = EmergingDraft(summary="pipeline", treatments=[
        EmergingCandidate(name="ABC-123", mechanism=None, potential_impact="p", trial_ids=["NCT00000001", "nct00000002"]),
        EmergingCandidate(name="Ghost", mechanism="made up", potential_impact="p", trial_ids=["NCT99999999"]),
    ])
    toolbox = FakeToolbox({"search_clinical_trials": {"trials": trials}})
    result = run(emerging.research(NSCLC, toolbox, FakeLLM({EmergingDraft: draft}), no_progress))

    assert [t.nct_id for t in result.section.trials] == ["NCT00000001", "NCT00000002"]
    (kept,) = result.section.treatments
    assert kept.name == "ABC-123"
    assert kept.trial_ids == ["NCT00000001", "NCT00000002"]
    assert kept.highest_phase == "Phase 3"  # from registry phases, not the model
    assert kept.sponsors == ["Acme Oncology", "University Hospital"]
    assert any("Ghost" in w for w in result.warnings)
    assert toolbox.calls[0][1]["phases"] == ["PHASE2", "PHASE3"]


def test_emerging_empty_and_failure_cases():
    llm = FakeLLM({})
    empty = run(emerging.research(NSCLC, FakeToolbox({"search_clinical_trials": {"trials": []}}), llm, no_progress))
    assert empty.section.treatments == [] and empty.failures == [] and "No active" in empty.warnings[0]

    timeout = ToolError("search_clinical_trials failed: Request 'tools/call' timed out")
    failed = run(emerging.research(NSCLC, FakeToolbox({"search_clinical_trials": timeout}), llm, no_progress))
    assert failed.section.treatments == [] and failed.warnings == [] and "timed out" in failed.failures[0]
    assert llm.calls == []


def test_mark_fda_labelled_distinguishes_approved_agents_from_investigational():
    def make(name: str) -> EmergingTreatment:
        return EmergingTreatment(name=name, mechanism=None, potential_impact="", trial_ids=["NCT00000001"], highest_phase="Phase 3", sponsors=[])

    treatments = [make("Pembrolizumab + ABC-123"), make("Ivonescimab"), make("Osimertinib with chemotherapy"), make("Pemetrexedine analog")]
    emerging.mark_fda_labelled(treatments, ["PEMBROLIZUMAB", "OSIMERTINIB MESYLATE", "PEMETREXED DISODIUM", "CARBOPLATIN, PACLITAXEL"])
    assert [t.fda_labelled_agents for t in treatments] == [["PEMBROLIZUMAB"], [], ["OSIMERTINIB"], []]


# ---------- organizations ----------

def test_organizations_aggregates_registry_sponsors_deterministically():
    trials = [
        trial("NCT00000001", sponsor="Acme Oncology", collaborators=[("National Cancer Institute (NCI)", "NIH")], interventions=["DRUG: ABC-123", "DRUG: Placebo"]),
        trial("NCT00000002", sponsor="Acme Oncology", interventions=["DRUG: ABC-456"]),
        trial("NCT00000003", sponsor="City University", sponsor_class="OTHER"),
    ]
    orgs = organizations.aggregate(trials)
    assert [(o.name, o.kind, len(o.trial_ids), o.lead_sponsor_count) for o in orgs] == [
        ("Acme Oncology", "Company", 2, 2),
        ("City University", "Academic / hospital", 1, 1),
        ("National Cancer Institute (NCI)", "NIH", 1, 0),
    ]
    assert orgs[0].interventions == ["ABC-123", "ABC-456"]  # placebo excluded


def test_organizations_failure_skips_llm():
    llm = FakeLLM({LandscapeSummary: LandscapeSummary(summary="x")})
    result = run(organizations.research(NSCLC, FakeToolbox({"search_clinical_trials": ToolError("down")}), llm, no_progress))
    assert llm.calls == [] and result.failures == ["down"] and result.section.organizations == []
