"""Streamlit UI — presentation only. Run with:  streamlit run app.py"""

import asyncio
import re
import time

import streamlit as st

from core import report
from core.briefing import BriefingError, generate_briefing
from core.config import get_settings

st.set_page_config(page_title="Medical Research Briefing", page_icon="🩺", layout="wide")

settings = get_settings()

with st.sidebar:
    st.header("Setup")
    if settings.openai_api_key:
        st.success("OpenAI API key configured")
    else:
        st.error("OPENAI_API_KEY missing — add it to `.env`")
    st.text(f"Model: {settings.openai_model}")
    st.markdown(
        "**Sources (via MCP)**\n"
        "- PubMed — guidelines & systematic reviews\n"
        "- openFDA — FDA drug labels\n"
        "- ClinicalTrials.gov — active trials"
    )
    st.caption("Research aid only — not medical advice.")

st.title("🩺 Medical Research Briefing")
st.caption("Enter a medical condition to get a sourced briefing on the standard of care, emerging treatments, and who is driving research.")

with st.form("condition_form"):
    query = st.text_input("Medical condition", placeholder="e.g. Type 2 diabetes, plaque psoriasis, idiopathic pulmonary fibrosis")
    submitted = st.form_submit_button("Generate briefing", type="primary", disabled=not settings.openai_api_key)

if submitted:
    st.session_state.pop("briefing", None)  # never show a stale briefing under a new error
    started = time.monotonic()
    with st.status("Generating briefing…", expanded=True) as status:
        def progress(message: str) -> None:
            status.update(label=f"{message}…")
            st.write(f"• {message}")

        try:
            briefing = asyncio.run(generate_briefing(query, progress))
            st.session_state["briefing"] = briefing
            partial = " (partial: some sources unavailable)" if briefing.source_failures else ""
            status.update(label=f"Briefing ready in {time.monotonic() - started:.0f}s{partial}", state="complete", expanded=False)
        except BriefingError as exc:
            status.update(label="Could not generate briefing", state="error", expanded=False)
            st.error(str(exc))
        except Exception as exc:  # last resort: keep the app alive and show details
            status.update(label="Unexpected error", state="error", expanded=False)
            st.error("Something went wrong while generating the briefing.")
            st.exception(exc)

briefing = st.session_state.get("briefing")
if briefing:
    st.header(f"Research briefing: {briefing.condition}")
    st.markdown(report.DISCLAIMER)

    if briefing.source_failures:
        st.warning("**Partial briefing:** some sources could not be reached, so related sections may be incomplete.\n\n" + report.failures_md(briefing))

    if briefing.warnings:
        with st.expander(f"⚠️ Data quality notes ({len(briefing.warnings)})"):
            st.markdown(report.warnings_md(briefing))

    tabs = st.tabs([
        "Executive summary",
        "Standard of care",
        f"Emerging treatments & trials ({len(briefing.emerging.trials)})",
        "Companies & institutions",
        f"References ({len(briefing.references)})",
    ])
    sections = [report.executive_md, report.standard_of_care_md, report.emerging_md, report.landscape_md, report.references_md]
    for tab, render in zip(tabs, sections):
        with tab:
            st.markdown(render(briefing))

    slug = re.sub(r"[^a-z0-9]+", "_", briefing.condition.lower()).strip("_")
    col_md, col_json = st.columns(2)
    col_md.download_button("⬇️ Download Markdown", report.to_markdown(briefing), file_name=f"briefing_{slug}.md", mime="text/markdown")
    col_json.download_button("⬇️ Download JSON", briefing.model_dump_json(indent=2), file_name=f"briefing_{slug}.json", mime="application/json")
