"""Shared data contracts between layers.

Two kinds of models:
- Source records (Reference, Trial, Organization) are built by code from API data, never by the LLM.
- LLM output models (*Draft, ConditionProfile, ExecutiveSummary, ...) are OpenAI structured-output
  schemas, so every field is required (use `| None` for values that may be unknown).
"""

from pydantic import BaseModel, Field

# ---------- Source records (from APIs) ----------


class Reference(BaseModel):
    id: str  # "PMID:12345678", "NCT01234567" or "FDA:<GENERIC NAME>"
    title: str
    url: str
    source: str  # "PubMed", "ClinicalTrials.gov", "openFDA"


class Collaborator(BaseModel):
    name: str
    sponsor_class: str


class Trial(BaseModel):
    nct_id: str
    title: str
    status: str
    phases: list[str]
    sponsor: str
    sponsor_class: str
    collaborators: list[Collaborator]
    interventions: list[str]
    primary_completion: str
    brief_summary: str
    url: str


class Organization(BaseModel):
    name: str
    kind: str  # "Company", "Academic / hospital", "NIH", ...
    trial_ids: list[str]
    lead_sponsor_count: int
    interventions: list[str]


# ---------- LLM output models ----------


class ConditionProfile(BaseModel):
    is_medical_condition: bool
    standard_name: str = Field(description="Common English clinical name, e.g. 'type 2 diabetes mellitus'")
    mesh_term: str = Field(description="MeSH descriptor if confident, else empty string")
    reason: str = Field(description="If not a medical condition, a short explanation for the user; else empty")


class CareTreatment(BaseModel):
    name: str
    category: str = Field(description="e.g. 'Drug class', 'Named drug', 'Procedure', 'Lifestyle'")
    role: str = Field(description="e.g. 'First-line', 'Add-on', 'Refractory disease', 'Surgical'")
    description: str
    citations: list[str] = Field(description="Source IDs from the evidence, e.g. PMID:12345678 or FDA:<NAME>")


class StandardOfCare(BaseModel):
    summary: str
    treatments: list[CareTreatment]


class EmergingCandidate(BaseModel):
    name: str
    mechanism: str | None = Field(description="Only if stated in the trial text, else null")
    potential_impact: str
    trial_ids: list[str] = Field(description="NCT IDs from the evidence")


class EmergingDraft(BaseModel):
    summary: str
    treatments: list[EmergingCandidate]


class LandscapeSummary(BaseModel):
    summary: str


class ExecutiveSummary(BaseModel):
    summary: str
    key_points: list[str]
    evidence_gaps: list[str]


# ---------- Verified briefing sections ----------


class EmergingTreatment(BaseModel):
    name: str
    mechanism: str | None
    potential_impact: str
    trial_ids: list[str]
    highest_phase: str  # derived from trial records
    sponsors: list[str]  # derived from trial records
    fda_labelled_agents: list[str] = Field(default_factory=list)  # derived: names matching FDA labels for this condition


class EmergingTreatments(BaseModel):
    summary: str
    treatments: list[EmergingTreatment]
    trials: list[Trial]


class Landscape(BaseModel):
    summary: str
    organizations: list[Organization]


class Briefing(BaseModel):
    query: str
    condition: str
    generated_at: str
    executive: ExecutiveSummary
    standard_of_care: StandardOfCare
    emerging: EmergingTreatments
    landscape: Landscape
    references: list[Reference]
    warnings: list[str]
    source_failures: list[str]
