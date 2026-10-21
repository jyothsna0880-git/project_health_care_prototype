"""Prompt templates and evidence formatting. Tune wording here without touching logic."""

import json

SOURCING_RULES = """Strict sourcing rules (non-negotiable):
- Use ONLY the evidence in the user message. Do not add drugs, trials, sponsors, results, dates,
  statistics or recommendations from outside knowledge.
- Cite only IDs that appear in the evidence, written exactly as given
  (PMID:12345678, NCT01234567, FDA:<GENERIC NAME>).
- If the evidence does not support a statement, leave it out or say it is not stated in the sources.
- Audience: a healthcare strategy team. Be clear and concise; no patient-specific advice."""

NORMALIZE_CONDITION = """You map a user's input to a medical condition for literature and trial searches.
- is_medical_condition: false if the input is not a disease, disorder, syndrome or clinical condition,
  or if it is too ambiguous to search (e.g. an abbreviation with several common meanings).
- standard_name: the common English clinical name (e.g. "type 2 diabetes mellitus", "plaque psoriasis").
- mesh_term: the exact MeSH descriptor if you are confident, else "".
- reason: when is_medical_condition is false, one sentence telling the user what to enter instead; else ""."""

STANDARD_OF_CARE = SOURCING_RULES + """

Task: summarize the CURRENT STANDARD OF CARE for the condition.
- summary: 3-5 sentences on the overall treatment approach described by the guidelines and reviews.
- treatments: the main options (drug classes, named drugs, procedures, lifestyle) with their role
  (e.g. first-line, add-on, refractory disease, surgical). Each needs at least one citation.
- Include FDA-labelled drugs only when their indication text is for this condition itself."""

EMERGING_TREATMENTS = SOURCING_RULES + """

Task: identify EMERGING TREATMENTS from the active Phase 2/3 clinical trials.
- Group trials by investigational intervention. Ignore placebo, standard-of-care comparators,
  and behavioural or diagnostic studies unless they are the main investigational approach.
- mechanism: only if stated in the trial text, else null.
- potential_impact: one sentence based on the trial design (population, phase, comparator).
  Do not claim efficacy; these are ongoing trials.
- At most 10 treatments, prioritising Phase 3 and novel agents. Each needs at least one NCT ID.
- summary: 2-4 sentences describing the pipeline overall."""

RESEARCH_LANDSCAPE = SOURCING_RULES + """

Task: in 3-5 sentences, describe which companies and research institutions are driving clinical
research on this condition and any focus areas visible in their interventions. Use only the
organization table provided (it is built from active trials on ClinicalTrials.gov)."""

EXECUTIVE_SUMMARY = SOURCING_RULES + """

Task: write the executive summary of a research briefing from the verified sections provided.
- summary: one paragraph (4-6 sentences) for a strategy audience.
- Keep established care (standard_of_care) and investigational treatments (emerging_treatments)
  clearly separate; never describe a trial agent as standard of care or approved.
- If a section is empty, say its evidence was unavailable; never fill it from general knowledge.
- key_points: 3-6 points. EVERY point must cite at least one source ID, one per bracket,
  e.g. [PMID:12345678] [NCT01234567] [FDA:OSIMERTINIB MESYLATE]. Points without IDs are discarded.
- evidence_gaps: what the evidence does not cover or where it is thin (consider the warnings)."""


def standard_of_care_input(condition: str, articles: list[dict], abstracts: str, drugs: list[dict]) -> str:
    return (
        f"Condition: {condition}\n\n"
        f"## PubMed guidelines and reviews (cite as PMID:<pmid>)\n{_json(articles)}\n\n"
        f"## Abstracts\n{abstracts or 'None retrieved.'}\n\n"
        f"## FDA drug labels (cite as FDA:<generic_name>)\n{_json(drugs)}"
    )


def emerging_input(condition: str, trials: list[dict]) -> str:
    return f"Condition: {condition}\n\n## Active Phase 2/3 trials (cite by nct_id)\n{_json(trials)}"


def landscape_input(condition: str, organizations: list[dict]) -> str:
    return f"Condition: {condition}\n\n## Organizations by number of active trials\n{_json(organizations)}"


def executive_input(condition: str, sections: dict, warnings: list[str]) -> str:
    return f"Condition: {condition}\n\n## Verified sections\n{_json(sections)}\n\n## Warnings\n{_json(warnings)}"


def _json(data) -> str:
    return json.dumps(data, indent=1, ensure_ascii=False)
