"""ClinicalTrials.gov v2 API — active interventional trials."""

from tools import http_client

BASE_URL = "https://clinicaltrials.gov/api/v2/studies"
ACTIVE_STATUSES = "RECRUITING,NOT_YET_RECRUITING,ACTIVE_NOT_RECRUITING,ENROLLING_BY_INVITATION"
VALID_PHASES = {"EARLY_PHASE1", "PHASE1", "PHASE2", "PHASE3", "PHASE4"}
MAX_PAGE_SIZE = 100
SUMMARY_CHARS = 400


def search_trials(condition: str, phases: list[str], max_results: int) -> list[dict]:
    phases = [p.upper().replace(" ", "") for p in phases]
    invalid = set(phases) - VALID_PHASES
    if invalid:
        raise ValueError(f"Invalid phases {sorted(invalid)}; use {sorted(VALID_PHASES)}")

    params = {
        "query.cond": http_client.clean_term(condition),
        "filter.overallStatus": ACTIVE_STATUSES,
        "filter.advanced": f"AREA[StudyType]INTERVENTIONAL AND AREA[Phase]({' OR '.join(phases)})",
        "sort": "LastUpdatePostDate:desc",
        "pageSize": min(max_results, MAX_PAGE_SIZE),
    }
    response = http_client.get(BASE_URL, params)
    response.raise_for_status()
    return [_summarize(study) for study in response.json().get("studies", [])]


def _summarize(study: dict) -> dict:
    protocol = study.get("protocolSection", {})
    ident = protocol.get("identificationModule", {})
    status = protocol.get("statusModule", {})
    sponsors = protocol.get("sponsorCollaboratorsModule", {})
    lead = sponsors.get("leadSponsor", {})
    interventions = protocol.get("armsInterventionsModule", {}).get("interventions", [])
    nct_id = ident.get("nctId", "")
    return {
        "nct_id": nct_id,
        "title": ident.get("briefTitle", ""),
        "status": status.get("overallStatus", ""),
        "phases": protocol.get("designModule", {}).get("phases", []),
        "sponsor": lead.get("name", ""),
        "sponsor_class": lead.get("class", ""),
        "collaborators": [{"name": c.get("name", ""), "sponsor_class": c.get("class", "")} for c in sponsors.get("collaborators", [])],
        "interventions": [f"{i.get('type', '')}: {i.get('name', '')}" for i in interventions],
        "primary_completion": status.get("primaryCompletionDateStruct", {}).get("date", ""),
        "brief_summary": protocol.get("descriptionModule", {}).get("briefSummary", "")[:SUMMARY_CHARS],
        "url": f"https://clinicaltrials.gov/study/{nct_id}",
    }
