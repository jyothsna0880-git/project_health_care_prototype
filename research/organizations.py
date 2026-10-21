"""Companies and research institutions: aggregated from sponsors/collaborators of active trials.

The organization table is built entirely from ClinicalTrials.gov data; the LLM only writes the summary.
"""

from core.schemas import ConditionProfile, Landscape, LandscapeSummary, Organization
from llm import prompts
from llm.client import LLMClient
from retrieval.mcp_client import Toolbox
from research.common import Progress, ResearchResult, fetch_list

MAX_TRIALS = 100
TOP_ORGANIZATIONS = 15
MAX_INTERVENTIONS = 5
SPONSOR_KINDS = {
    "INDUSTRY": "Company",
    "OTHER": "Academic / hospital",
    "NIH": "NIH",
    "FED": "US federal agency",
    "OTHER_GOV": "Government",
    "NETWORK": "Research network",
    "INDIV": "Individual investigator",
}


async def research(
    profile: ConditionProfile, toolbox: Toolbox, llm: LLMClient, progress: Progress
) -> ResearchResult[Landscape]:
    result = ResearchResult(section=Landscape(summary="", organizations=[]))

    progress("Companies & institutions: scanning sponsors of active trials (all phases)")
    trials = await fetch_list(
        toolbox, "search_clinical_trials",
        {"condition": profile.standard_name, "phases": ["EARLY_PHASE1", "PHASE1", "PHASE2", "PHASE3"], "max_results": MAX_TRIALS},
        "trials", result.failures,
    )
    organizations = aggregate(trials)[:TOP_ORGANIZATIONS]
    result.section.organizations = organizations

    if not organizations:
        if not result.failures:
            result.warnings.append("No trial sponsors were found, so the research landscape could not be described.")
        return result

    progress(f"Companies & institutions: summarizing {len(organizations)} most active organizations")
    draft = await llm.structured(
        prompts.RESEARCH_LANDSCAPE,
        prompts.landscape_input(profile.standard_name, [o.model_dump() for o in organizations]),
        LandscapeSummary,
    )
    result.section.summary = draft.summary
    return result


def aggregate(trials: list[dict]) -> list[Organization]:
    """Group trials by lead sponsor and collaborators, most active first."""
    organizations: dict[str, Organization] = {}
    for trial in trials:
        parties = [(trial["sponsor"], trial["sponsor_class"], True)]
        parties += [(c["name"], c["sponsor_class"], False) for c in trial["collaborators"]]
        for name, sponsor_class, is_lead in parties:
            if not name:
                continue
            org = organizations.setdefault(name, Organization(
                name=name, kind=SPONSOR_KINDS.get(sponsor_class, "Other"), trial_ids=[], lead_sponsor_count=0, interventions=[]
            ))
            if trial["nct_id"] in org.trial_ids:
                continue
            org.trial_ids.append(trial["nct_id"])
            org.lead_sponsor_count += is_lead
            for intervention in trial["interventions"]:
                name_only = intervention.split(": ", 1)[-1]
                if "placebo" not in name_only.lower() and name_only not in org.interventions:
                    org.interventions.append(name_only)
    for org in organizations.values():
        org.interventions = org.interventions[:MAX_INTERVENTIONS]
    return sorted(organizations.values(), key=lambda o: (-len(o.trial_ids), o.name))
