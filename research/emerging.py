"""Emerging treatments: active Phase 2/3 trials from ClinicalTrials.gov."""

import re

from core.citations import verify
from core.schemas import ConditionProfile, EmergingDraft, EmergingTreatment, EmergingTreatments, Reference, Trial
from llm import prompts
from llm.client import LLMClient
from retrieval.mcp_client import Toolbox
from research.common import Progress, ResearchResult, fetch_list, highest_phase

MAX_TRIALS = 30
MIN_AGENT_NAME = 5  # ignore short fragments that would match unrelated words


async def research(
    profile: ConditionProfile, toolbox: Toolbox, llm: LLMClient, progress: Progress
) -> ResearchResult[EmergingTreatments]:
    result = ResearchResult(section=EmergingTreatments(summary="", treatments=[], trials=[]))
    condition = profile.standard_name

    progress("Emerging treatments: searching ClinicalTrials.gov for active Phase 2/3 trials")
    raw_trials = await fetch_list(
        toolbox, "search_clinical_trials",
        {"condition": condition, "phases": ["PHASE2", "PHASE3"], "max_results": MAX_TRIALS}, "trials", result.failures,
    )
    trials = [Trial.model_validate(t) for t in raw_trials]
    result.section.trials = trials
    for t in trials:
        result.sources[t.nct_id] = Reference(id=t.nct_id, title=t.title, url=t.url, source="ClinicalTrials.gov")

    if not trials:
        if not result.failures:
            result.warnings.append("No active Phase 2/3 interventional trials were found on ClinicalTrials.gov.")
        return result

    progress(f"Emerging treatments: analysing {len(trials)} trials")
    draft = await llm.structured(prompts.EMERGING_TREATMENTS, prompts.emerging_input(condition, raw_trials), EmergingDraft)

    by_id = {t.nct_id: t for t in trials}
    for candidate in draft.treatments:
        trial_ids, unverified = verify(candidate.trial_ids, result.sources)
        if unverified:
            result.warnings.append(f"Removed unverifiable trial ID(s) {unverified} from '{candidate.name}'.")
        if not trial_ids:
            result.warnings.append(f"Removed '{candidate.name}' from emerging treatments: no verifiable trial.")
            continue
        linked = [by_id[i] for i in trial_ids]
        result.section.treatments.append(EmergingTreatment(
            name=candidate.name,
            mechanism=candidate.mechanism,
            potential_impact=candidate.potential_impact,
            trial_ids=trial_ids,
            highest_phase=highest_phase([t.phases for t in linked]),
            sponsors=sorted({t.sponsor for t in linked if t.sponsor}),
        ))
    result.section.summary = draft.summary
    return result


def mark_fda_labelled(treatments: list[EmergingTreatment], fda_generic_names: list[str]) -> None:
    """Flag agents in an emerging treatment's name that already have an FDA label for this condition,
    so a new combination of an approved drug is not presented as a wholly new treatment."""
    agents = {_base_agent(component) for name in fda_generic_names for component in re.split(r",| AND ", name)}
    agents = {a for a in agents if len(a) >= MIN_AGENT_NAME}
    for treatment in treatments:
        treatment.fda_labelled_agents = sorted(a for a in agents if re.search(rf"\b{re.escape(a)}\b", treatment.name, re.IGNORECASE))


def _base_agent(generic_name: str) -> str:
    """'OSIMERTINIB MESYLATE' -> 'OSIMERTINIB'; 'ADALIMUMAB-AACF' (biosimilar) -> 'ADALIMUMAB'."""
    words = generic_name.strip().split()
    return words[0].split("-")[0].upper() if words else ""
