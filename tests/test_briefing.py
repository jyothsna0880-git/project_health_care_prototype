"""Pipeline: credentials, input validation, failures, never reporting a fabricated success."""

import asyncio
from contextlib import asynccontextmanager

import httpx
import openai
import pytest

from conftest import NSCLC, FakeLLM, FakeToolbox, article, drug, trial
from core import briefing
from core.briefing import BriefingError, generate_briefing
from core.schemas import (
    CareTreatment, ConditionProfile, EmergingCandidate, EmergingDraft, ExecutiveSummary, LandscapeSummary, StandardOfCare,
)
from retrieval.mcp_client import ToolError

GOOD_TOOLS = {
    "search_guidelines_and_reviews": {"articles": [article("11111111")]},
    "get_pubmed_abstracts": "abstract",
    "search_approved_drugs": {"drugs": [drug("PEMBROLIZUMAB")]},
    "search_clinical_trials": {"trials": [trial("NCT00000001")]},
}


def llm_outputs(overrides: dict | None = None) -> dict:
    outputs = {
        ConditionProfile: NSCLC,
        StandardOfCare: StandardOfCare(summary="soc", treatments=[
            CareTreatment(name="Pembrolizumab", category="Named drug", role="First-line", description="d", citations=["PMID:11111111", "FDA:PEMBROLIZUMAB"]),
        ]),
        EmergingDraft: EmergingDraft(summary="pipe", treatments=[
            EmergingCandidate(name="Pembrolizumab + ABC-123", mechanism=None, potential_impact="p", trial_ids=["NCT00000001"]),
        ]),
        LandscapeSummary: LandscapeSummary(summary="landscape"),
        ExecutiveSummary: ExecutiveSummary(summary="exec", key_points=[
            "Pembrolizumab is first-line [PMID:11111111]",
            "Uncited claim with no source",
            "Fake claim [NCT99999999]",
        ], evidence_gaps=[]),
    }
    return {**outputs, **(overrides or {})}


@pytest.fixture
def wire(monkeypatch, no_env_file):
    """Replace OpenAI and the MCP server with fakes; everything else is real."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    def install(tools: dict, outputs: dict) -> FakeLLM:
        llm = FakeLLM(outputs)

        @asynccontextmanager
        async def connect():
            yield FakeToolbox(tools)

        monkeypatch.setattr(briefing.mcp_client, "connect", connect)
        monkeypatch.setattr(briefing, "LLMClient", lambda *args: llm)
        return llm

    return install


def generate(query: str = "NSCLC"):
    return asyncio.run(generate_briefing(query))


def test_full_pipeline_success_and_validation(wire):
    wire(GOOD_TOOLS, llm_outputs())
    b = generate()

    assert b.condition == "non-small cell lung cancer"
    assert b.source_failures == []
    assert b.executive.key_points == ["Pembrolizumab is first-line [PMID:11111111]"]
    assert any("no source ID" in w for w in b.warnings) and any("NCT99999999" in w for w in b.warnings)
    assert [r.id for r in b.references] == ["PMID:11111111", "FDA:PEMBROLIZUMAB", "NCT00000001"]
    # established vs investigational
    assert all(not c.startswith("NCT") for t in b.standard_of_care.treatments for c in t.citations)
    assert all(i.startswith("NCT") for t in b.emerging.treatments for i in t.trial_ids)
    assert b.emerging.treatments[0].fda_labelled_agents == ["PEMBROLIZUMAB"]


def test_missing_credentials(monkeypatch, no_env_file):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(BriefingError, match="OPENAI_API_KEY is not set"):
        generate()


@pytest.mark.parametrize("query", ["", "   ", "x" * 201])
def test_invalid_input(wire, query):
    wire(GOOD_TOOLS, llm_outputs())
    with pytest.raises(BriefingError, match="Enter a medical condition"):
        generate(query)


def test_non_medical_input_is_rejected(wire):
    rejected = ConditionProfile(is_medical_condition=False, standard_name="", mesh_term="", reason="Enter a disease name.")
    wire(GOOD_TOOLS, llm_outputs({ConditionProfile: rejected}))
    with pytest.raises(BriefingError, match="Enter a disease name"):
        generate("banana")


def test_all_sources_down_never_returns_a_briefing(wire):
    down = ToolError("timed out")
    llm = wire({name: down for name in GOOD_TOOLS}, llm_outputs())
    with pytest.raises(BriefingError, match="could not be reached"):
        generate()
    assert ExecutiveSummary not in llm.calls


def test_nothing_found_is_reported_as_not_found(wire):
    empty = {"search_guidelines_and_reviews": {"articles": []}, "search_approved_drugs": {"drugs": []}, "search_clinical_trials": {"trials": []}}
    wire(empty, llm_outputs())
    with pytest.raises(BriefingError, match="No publications, drug labels or trials were found"):
        generate()


def test_trials_down_gives_partial_briefing_without_emerging_content(wire):
    wire({**GOOD_TOOLS, "search_clinical_trials": ToolError("search_clinical_trials failed: HTTP 503")}, llm_outputs())
    b = generate()
    assert b.source_failures == ["search_clinical_trials failed: HTTP 503"] * 2  # emerging + organizations
    assert b.emerging.treatments == [] and b.emerging.trials == [] and b.landscape.organizations == []
    assert b.standard_of_care.treatments  # the available source is still used


def openai_error(cls, status: int):
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    return cls("err", response=httpx.Response(status, request=request), body=None)


@pytest.mark.parametrize(("error", "message"), [
    (openai_error(openai.AuthenticationError, 401), "rejected the API key"),
    (openai_error(openai.NotFoundError, 404), "cannot use model"),
    (openai_error(openai.RateLimitError, 429), "rate limit or quota"),
    (openai.APITimeoutError(request=httpx.Request("POST", "https://api.openai.com")), "Could not reach OpenAI"),
    (ExceptionGroup("tg", [ExceptionGroup("tg", [ToolError("x failed")])]), "MCP research tools failed: x failed"),
    (TimeoutError(), "timed out"),
])
def test_errors_are_translated_for_users(wire, error, message):
    def boom(_user):
        raise error
    wire(GOOD_TOOLS, llm_outputs({ConditionProfile: boom}))
    with pytest.raises(BriefingError, match=message):
        generate()
