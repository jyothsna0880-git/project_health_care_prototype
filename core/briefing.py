"""Briefing pipeline — the only module that wires the layers together.

condition -> normalize (LLM) -> [standard of care | emerging | organizations] in parallel (MCP + LLM)
          -> executive summary (LLM) -> verified Briefing
"""

import asyncio
from datetime import date

import openai
from mcp import MCPError

from core.citations import ids_in_text
from core.config import get_settings
from core.schemas import Briefing, ConditionProfile, ExecutiveSummary, Reference
from llm import prompts
from llm.client import LLMClient
from research import emerging, organizations, standard_of_care
from research.common import Progress
from retrieval import mcp_client
from retrieval.mcp_client import ToolError

MAX_QUERY_LENGTH = 200


class BriefingError(Exception):
    """A failure with a message that is safe and useful to show the user."""


async def generate_briefing(query: str, progress: Progress = lambda _: None) -> Briefing:
    query = query.strip()
    if not query or len(query) > MAX_QUERY_LENGTH:
        raise BriefingError(f"Enter a medical condition (1–{MAX_QUERY_LENGTH} characters).")

    settings = get_settings()
    if not settings.openai_api_key:
        raise BriefingError("OPENAI_API_KEY is not set. Add it to the .env file in the project folder.")
    llm = LLMClient(settings.openai_api_key, settings.openai_model, settings.openai_timeout)

    try:
        return await _run(query, llm, progress)
    except Exception as exc:
        raise _user_facing(exc, settings.openai_model) from exc


async def _run(query: str, llm: LLMClient, progress: Progress) -> Briefing:
    progress("Identifying the condition")
    profile = await llm.structured(prompts.NORMALIZE_CONDITION, query, ConditionProfile)
    if not profile.is_medical_condition:
        raise BriefingError(profile.reason or f"'{query}' does not look like a medical condition.")
    progress(f"Condition: {profile.standard_name}" + (f" (MeSH: {profile.mesh_term})" if profile.mesh_term else ""))

    progress("Starting MCP research tools server")
    async with mcp_client.connect() as toolbox:
        care, pipeline, landscape = await asyncio.gather(
            standard_of_care.research(profile, toolbox, llm, progress),
            emerging.research(profile, toolbox, llm, progress),
            organizations.research(profile, toolbox, llm, progress),
        )

    sources = {**care.sources, **pipeline.sources}
    warnings = care.warnings + pipeline.warnings + landscape.warnings
    failures = care.failures + pipeline.failures + landscape.failures
    if not care.sources and not pipeline.sources:
        if failures:
            raise BriefingError("The research sources could not be reached, so no briefing was produced: " + "; ".join(failures))
        raise BriefingError(f"No publications, drug labels or trials were found for '{profile.standard_name}'. Try a more specific or common name.")

    fda_names = [ref_id.removeprefix("FDA:") for ref_id in care.sources if ref_id.startswith("FDA:")]
    emerging.mark_fda_labelled(pipeline.section.treatments, fda_names)

    progress("Writing executive summary")
    sections = {
        "standard_of_care": care.section.model_dump(),
        "emerging_treatments": pipeline.section.model_dump(exclude={"trials"}),
        "research_landscape": landscape.section.model_dump(),
    }
    executive = await llm.structured(
        prompts.EXECUTIVE_SUMMARY, prompts.executive_input(profile.standard_name, sections, warnings + failures), ExecutiveSummary
    )
    executive = _drop_unverified_points(executive, sources, warnings)

    cited = [c for t in care.section.treatments for c in t.citations]
    cited += [i for t in pipeline.section.treatments for i in t.trial_ids]
    cited += [i for point in executive.key_points for i in ids_in_text(point)]

    return Briefing(
        query=query,
        condition=profile.standard_name,
        generated_at=date.today().isoformat(),
        executive=executive,
        standard_of_care=care.section,
        emerging=pipeline.section,
        landscape=landscape.section,
        references=_references(cited, sources),
        warnings=warnings,
        source_failures=failures,
    )


def _drop_unverified_points(executive: ExecutiveSummary, sources: dict[str, Reference], warnings: list[str]) -> ExecutiveSummary:
    """Keep only key points that cite at least one source ID, all of them verified."""
    kept = []
    for point in executive.key_points:
        ids = ids_in_text(point)
        unknown = [i for i in ids if i not in sources]
        if not ids:
            warnings.append(f"Removed an executive summary point with no source ID: '{point}'")
        elif unknown:
            warnings.append(f"Removed an executive summary point citing unverifiable ID(s) {unknown}.")
        else:
            kept.append(point)
    return executive.model_copy(update={"key_points": kept})


def _references(cited: list[str], sources: dict[str, Reference]) -> list[Reference]:
    return [sources[i] for i in dict.fromkeys(cited) if i in sources]


def _user_facing(exc: BaseException, model: str) -> BriefingError:
    """Unwrap anyio/MCP exception groups and translate known failures into readable messages."""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]

    if isinstance(exc, BriefingError):
        return exc
    if isinstance(exc, openai.AuthenticationError):
        return BriefingError("OpenAI rejected the API key. Check OPENAI_API_KEY in .env.")
    if isinstance(exc, openai.PermissionDeniedError | openai.NotFoundError):
        return BriefingError(f"Your OpenAI account cannot use model '{model}'. Set OPENAI_MODEL in .env to a model you have access to.")
    if isinstance(exc, openai.RateLimitError):
        return BriefingError("OpenAI rate limit or quota exceeded. Wait a minute or check your billing, then try again.")
    if isinstance(exc, openai.APIConnectionError):  # includes timeouts
        return BriefingError("Could not reach OpenAI. Check your internet connection and try again.")
    if isinstance(exc, openai.APIError):
        return BriefingError(f"OpenAI error: {exc}")
    if isinstance(exc, ToolError | MCPError):
        return BriefingError(f"The MCP research tools failed: {exc}")
    if isinstance(exc, TimeoutError):
        return BriefingError("A research source timed out. Try again in a moment.")
    return BriefingError(f"Unexpected error ({type(exc).__name__}): {exc}")
