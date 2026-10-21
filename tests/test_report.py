from core import report
from core.schemas import (
    Briefing, CareTreatment, EmergingTreatment, EmergingTreatments, ExecutiveSummary, Landscape, Reference, StandardOfCare, Trial,
)


def make_briefing(**overrides) -> Briefing:
    data = dict(
        query="NSCLC", condition="non-small cell lung cancer", generated_at="2026-10-21",
        executive=ExecutiveSummary(summary="exec", key_points=["Point [PMID:11111111] [FDA:PEMBROLIZUMAB]"], evidence_gaps=[]),
        standard_of_care=StandardOfCare(summary="soc", treatments=[
            CareTreatment(name="Platinum | doublet", category="Drug class", role="First-line", description="line1\nline2", citations=["PMID:11111111"]),
        ]),
        emerging=EmergingTreatments(summary="pipe", treatments=[
            EmergingTreatment(name="ABC-123", mechanism=None, potential_impact="p", trial_ids=["NCT00000001"], highest_phase="Phase 3", sponsors=["Acme"]),
            EmergingTreatment(name="Pembrolizumab + X", mechanism="PD-1", potential_impact="p", trial_ids=["NCT00000001"], highest_phase="Phase 2", sponsors=[], fda_labelled_agents=["PEMBROLIZUMAB"]),
        ], trials=[Trial(nct_id="NCT00000001", title="T", status="RECRUITING", phases=["PHASE3"], sponsor="Acme", sponsor_class="INDUSTRY",
                         collaborators=[], interventions=[], primary_completion="2028", brief_summary="", url="https://clinicaltrials.gov/study/NCT00000001")]),
        landscape=Landscape(summary="", organizations=[]),
        references=[
            Reference(id="PMID:11111111", title="G", url="https://pubmed.ncbi.nlm.nih.gov/11111111/", source="PubMed"),
            Reference(id="FDA:PEMBROLIZUMAB", title="L", url="https://dailymed.nlm.nih.gov/x", source="openFDA"),
            Reference(id="NCT00000001", title="T", url="https://clinicaltrials.gov/study/NCT00000001", source="ClinicalTrials.gov"),
        ],
        warnings=[], source_failures=[],
    )
    return Briefing(**{**data, **overrides})


def test_sections_label_established_vs_investigational():
    b = make_briefing()
    assert "Established care" in report.standard_of_care_md(b)
    emerging = report.emerging_md(b)
    assert "Investigational" in emerging and "New use/combination of FDA-labelled Pembrolizumab" in emerging
    assert "Not stated in sources" in emerging


def test_tables_are_escaped_and_citations_linked():
    b = make_briefing()
    assert "Platinum \\| doublet" in report.standard_of_care_md(b) and "line1 line2" in report.standard_of_care_md(b)
    executive = report.executive_md(b)
    assert "[PMID:11111111](https://pubmed.ncbi.nlm.nih.gov/11111111/)" in executive
    assert "[FDA:PEMBROLIZUMAB](https://dailymed.nlm.nih.gov/x)" in executive


def test_full_markdown_shows_partial_banner_only_on_failures():
    assert "Partial briefing" not in report.to_markdown(make_briefing())
    assert "Partial briefing" in report.to_markdown(make_briefing(source_failures=["openfda timed out"]))
