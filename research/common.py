"""Shared types and helpers for the research functions."""

from collections.abc import Callable
from dataclasses import dataclass, field

from core.schemas import Reference
from retrieval.mcp_client import Toolbox, ToolError

Progress = Callable[[str], None]

PHASE_ORDER = ["EARLY_PHASE1", "PHASE1", "PHASE2", "PHASE3", "PHASE4"]


@dataclass
class ResearchResult[T]:
    section: T
    sources: dict[str, Reference] = field(default_factory=dict)  # every record retrieved, keyed by citation ID
    warnings: list[str] = field(default_factory=list)  # data-quality notes: nothing found, citations removed
    failures: list[str] = field(default_factory=list)  # sources that could not be reached (errors, timeouts)


async def fetch_list(toolbox: Toolbox, tool: str, arguments: dict, key: str, failures: list[str]) -> list[dict]:
    """Call a tool returning {key: [...]}; on failure record it and return [] so other sources still run."""
    try:
        return (await toolbox.call_json(tool, arguments)).get(key, [])
    except ToolError as exc:
        failures.append(str(exc))
        return []


def format_phase(phase: str) -> str:
    return phase.replace("EARLY_PHASE1", "Early Phase 1").replace("PHASE", "Phase ")


def highest_phase(phase_lists: list[list[str]]) -> str:
    phases = {p for phases in phase_lists for p in phases if p in PHASE_ORDER}
    return format_phase(max(phases, key=PHASE_ORDER.index)) if phases else "Not stated"
