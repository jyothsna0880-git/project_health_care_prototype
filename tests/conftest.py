"""Shared fakes. Unit tests replace only the MCP toolbox and OpenAI; all validation code runs for real."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.schemas import ConditionProfile  # noqa: E402

NSCLC = ConditionProfile(
    is_medical_condition=True,
    standard_name="non-small cell lung cancer",
    mesh_term="Carcinoma, Non-Small-Cell Lung",
    reason="",
)


class FakeToolbox:
    """Stands in for retrieval.mcp_client.Toolbox. Values may be data, an exception, or a callable(args)."""

    def __init__(self, responses: dict):
        self.responses = responses
        self.calls: list[tuple[str, dict]] = []

    async def call_json(self, name: str, arguments: dict):
        return self._respond(name, arguments, default={})

    async def call_text(self, name: str, arguments: dict):
        return self._respond(name, arguments, default="")

    def _respond(self, name, arguments, default):
        self.calls.append((name, arguments))
        response = self.responses.get(name, default)
        if isinstance(response, Exception):
            raise response
        return response(arguments) if callable(response) else response


class FakeLLM:
    """Stands in for llm.client.LLMClient. Maps output schema -> instance or callable(user_message)."""

    def __init__(self, outputs: dict):
        self.outputs = outputs
        self.calls: list[type] = []

    async def structured(self, system: str, user: str, schema: type):
        self.calls.append(schema)
        output = self.outputs[schema]
        return output(user) if callable(output) else output


def trial(nct_id: str, phases=("PHASE3",), sponsor="Acme Oncology", sponsor_class="INDUSTRY", collaborators=(), interventions=("DRUG: ABC-123",)) -> dict:
    return {
        "nct_id": nct_id,
        "title": f"Study {nct_id}",
        "status": "RECRUITING",
        "phases": list(phases),
        "sponsor": sponsor,
        "sponsor_class": sponsor_class,
        "collaborators": [{"name": n, "sponsor_class": c} for n, c in collaborators],
        "interventions": list(interventions),
        "primary_completion": "2028-01",
        "brief_summary": "",
        "url": f"https://clinicaltrials.gov/study/{nct_id}",
    }


def article(pmid: str) -> dict:
    return {"pmid": pmid, "title": f"Guideline {pmid}", "journal": "J", "pub_date": "2024", "pub_types": ["Practice Guideline"], "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"}


def drug(generic: str) -> dict:
    return {"generic_name": generic, "brand_names": [], "pharm_class": [], "indication_excerpt": "non-small cell lung cancer", "url": "https://dailymed.nlm.nih.gov/x"}


@pytest.fixture
def no_env_file(monkeypatch, tmp_path):
    """Isolate tests from a developer's real .env."""
    monkeypatch.setattr("core.config.ENV_FILE", tmp_path / "missing.env")
