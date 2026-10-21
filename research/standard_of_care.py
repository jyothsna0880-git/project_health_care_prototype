"""Standard of care: PubMed guidelines/reviews + FDA drug labels."""

from core.citations import verify
from core.schemas import CareTreatment, ConditionProfile, Reference, StandardOfCare
from llm import prompts
from llm.client import LLMClient
from retrieval.mcp_client import Toolbox, ToolError
from research.common import Progress, ResearchResult, fetch_list

ABSTRACTS_TO_READ = 5
MAX_ABSTRACT_CHARS = 24_000


async def research(
    profile: ConditionProfile, toolbox: Toolbox, llm: LLMClient, progress: Progress
) -> ResearchResult[StandardOfCare]:
    result = ResearchResult(section=StandardOfCare(summary="", treatments=[]))
    condition = profile.standard_name

    progress("Standard of care: searching PubMed for guidelines and systematic reviews")
    articles = await fetch_list(
        toolbox, "search_guidelines_and_reviews",
        {"condition": condition, "mesh_term": profile.mesh_term}, "articles", result.failures,
    )

    abstracts = ""
    if articles:
        progress(f"Standard of care: reading the top {min(len(articles), ABSTRACTS_TO_READ)} abstracts")
        try:
            pmids = [a["pmid"] for a in articles[:ABSTRACTS_TO_READ]]
            abstracts = (await toolbox.call_text("get_pubmed_abstracts", {"pmids": pmids}))[:MAX_ABSTRACT_CHARS]
        except ToolError as exc:
            result.failures.append(str(exc))

    progress("Standard of care: checking FDA drug labels (openFDA)")
    drugs = await fetch_list(toolbox, "search_approved_drugs", {"condition": condition}, "drugs", result.failures)

    for a in articles:
        result.sources[f"PMID:{a['pmid']}"] = Reference(id=f"PMID:{a['pmid']}", title=a["title"], url=a["url"], source="PubMed")
    for d in drugs:
        brands = f" ({', '.join(d['brand_names'][:3])})" if d["brand_names"] else ""
        result.sources[f"FDA:{d['generic_name']}"] = Reference(
            id=f"FDA:{d['generic_name']}", title=f"FDA drug label: {d['generic_name'].title()}{brands}", url=d["url"], source="openFDA"
        )

    if not result.sources:
        if not result.failures:
            result.warnings.append("No guidelines, reviews or FDA labels were found, so the standard of care could not be summarized.")
        return result

    progress("Standard of care: synthesizing findings")
    draft = await llm.structured(
        prompts.STANDARD_OF_CARE, prompts.standard_of_care_input(condition, articles, abstracts, drugs), StandardOfCare
    )
    result.section = StandardOfCare(summary=draft.summary, treatments=_verified(draft.treatments, result))
    return result


def _verified(treatments: list[CareTreatment], result: ResearchResult) -> list[CareTreatment]:
    kept = []
    for treatment in treatments:
        citations, unverified = verify(treatment.citations, result.sources)
        if unverified:
            result.warnings.append(f"Removed unverifiable citation(s) {unverified} from '{treatment.name}'.")
        if citations:
            kept.append(treatment.model_copy(update={"citations": citations}))
        else:
            result.warnings.append(f"Removed '{treatment.name}' from standard of care: no verifiable source.")
    return kept
