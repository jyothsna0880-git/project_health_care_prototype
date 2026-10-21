# Medical Research Briefing

A local Streamlit app for a healthcare strategy team. Enter a medical condition and get a sourced, structured briefing:

- **Executive summary**: key points and evidence gaps
- **Current standard of care**: from clinical practice guidelines, systematic reviews and FDA drug labels
- **Emerging treatments & trials**: from active Phase 2/3 trials
- **Companies & research institutions**: who sponsors active trials
- **References**: every citation links to PubMed, ClinicalTrials.gov or DailyMed

Stack: Python 3.12+, Streamlit, OpenAI SDK (structured outputs), MCP (official `mcp` SDK, stdio).

## Run it

```powershell
python -m venv .venv
.venv\Scripts\activate                  # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env                  # macOS/Linux: cp .env.example .env
# edit .env and set OPENAI_API_KEY
streamlit run app.py
```

Open http://localhost:8501, type a condition (e.g. `idiopathic pulmonary fibrosis`) and click **Generate briefing**.
A briefing typically takes 30–90 seconds. Live progress is shown while it runs.

### Configuration (`.env`)

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `OPENAI_API_KEY` | yes | — | OpenAI API key |
| `OPENAI_MODEL` | no | `gpt-4.1` | Any OpenAI model that supports structured outputs |
| `NCBI_API_KEY` | no | — | Raises PubMed rate limit (3 → 10 req/s) |

`.env` is re-read on every run, so edits apply without restarting Streamlit. Values in `.env` override shell variables.

## How it works

```
app.py (Streamlit UI)
  └─ core/briefing.generate_briefing(query)
       1. Normalize condition          LLM → standard name + MeSH term (rejects non-conditions)
       2. Start MCP server (stdio)     retrieval/mcp_client → tools/server.py
       3. Research in parallel:
            research/standard_of_care  PubMed guidelines + abstracts, openFDA labels → LLM → verify citations
            research/emerging          ClinicalTrials.gov Phase 2/3 active trials  → LLM → verify trial IDs
            research/organizations     sponsors/collaborators of active trials (aggregated in code) → LLM summary
       4. Executive summary            LLM over the verified sections → verify IDs
       5. Briefing                     one Pydantic model → core/report renders Markdown
```

### Data sources (all public, no key needed)

| Source | Used for | Tool on the MCP server |
|---|---|---|
| PubMed (NCBI E-utilities) | Practice guidelines first, then treatment-focused systematic reviews/meta-analyses (last 5 years) | `search_guidelines_and_reviews`, `get_pubmed_abstracts` |
| openFDA drug labels | FDA-approved drugs whose labelled indication matches | `search_approved_drugs` |
| ClinicalTrials.gov v2 | Active interventional trials (recruiting / ongoing) | `search_clinical_trials` |

### No invented facts, trials or citations

The model may only use evidence retrieved in the current run, and the code enforces this:

1. **Prompts** restrict the model to the supplied evidence and to IDs that appear in it.
2. **Citation verification** ([core/citations.py](core/citations.py)): every PMID, NCT ID and FDA ID the model returns is checked against the records actually retrieved. Unverifiable IDs are removed, along with any treatment or key point left without a verifiable source. Each removal is listed under **Data quality notes**.
3. **Facts from data, not the model:** trial phases, statuses, sponsors, completion dates, the trials table, the organizations table and all reference titles/URLs come straight from the APIs.
4. **No evidence, no section:** if a source returns nothing, the model is not called for that section and the briefing says so.
5. **Executive summary:** every key point must cite at least one ID, and every cited ID must be verified; other points are dropped.

### Established vs investigational treatments

- **Standard of care** may cite only PubMed guidelines/reviews and FDA labels. A trial ID cited there is rejected.
- **Emerging treatments** may cite only trials retrieved from ClinicalTrials.gov, and are labelled *Investigational*.
- When an emerging treatment's name contains a drug with an FDA label for the condition (e.g. *pembrolizumab + new agent*),
  the code labels it *New use/combination of FDA-labelled …*, so it is not presented as a wholly new drug.

## Project structure

```
app.py                       Streamlit UI: input, progress, tabs, downloads
core/
  config.py                  Settings from .env
  schemas.py                 All data contracts (source records, LLM outputs, Briefing)
  briefing.py                Pipeline orchestration + user-facing error translation
  citations.py               Citation ID normalization and verification
  report.py                  Briefing → Markdown (per tab and full download)
research/
  common.py                  ResearchResult, safe tool fetch, phase helpers
  standard_of_care.py        Standard of care research function
  emerging.py                Emerging treatments research function
  organizations.py           Companies & institutions research function
llm/
  client.py                  OpenAI structured-output call (no MCP knowledge)
  prompts.py                 All prompts and evidence formatting
retrieval/
  mcp_client.py              Launches the MCP server, calls tools (no LLM knowledge)
tools/
  server.py                  MCP server: registers the tools
  pubmed.py · openfda.py · clinical_trials.py   One public API each
  http_client.py             Shared GET with timeout + retry on 429/5xx
```

Dependency direction: `app → core.briefing → research → (llm, retrieval) → tools`. Only `core/briefing.py` wires the layers together.

## Error handling

| Situation | What the user sees |
|---|---|
| Missing API key | Sidebar error; Generate button disabled |
| Invalid key / no model access / rate limit / network | A specific message in the app (no stack trace) |
| Input is not a medical condition | The model's explanation of what to enter instead |
| One source down or timed out (e.g. openFDA) | Briefing generated and marked **Partial**, with a visible banner naming the failed source; affected sections stay empty |
| Every source down | Error: sources could not be reached; **no briefing is produced** |
| Nothing found in any source | Message suggesting a more specific or common name (distinct from "unreachable") |

Timeouts: 20 s per HTTP request (retried on 429/5xx), 90 s per MCP tool call, 120 s per OpenAI call.

## Tests

```powershell
pytest -m "not live"     # 36 offline tests: fake MCP + fake OpenAI, all validation code real (~15 s)
pytest -m live -s        # 5 live tests: real MCP server + PubMed/openFDA/ClinicalTrials.gov, NSCLC (~1 min)
pytest                   # everything
```

No OpenAI key is needed for the tests. The live tests use non-small cell lung cancer and check that:
- every retrieved trial's ID, title, status, phases and lead sponsor match its registry record, fetched separately by NCT ID;
- all trials are active and Phase 2/3, and every PMID resolves to the same PubMed title;
- empty searches return empty lists; bad arguments and timeouts raise readable `ToolError`s;
- the full pipeline over real data drops invented PMIDs, NCT IDs, treatments and uncited summary points.

`tests/test_app.py` also starts the real Streamlit server and checks its health endpoint.

## Extending

- **New data source:** add `tools/<source>.py`, register it in `tools/server.py`, and call it from a research function.
- **Using the tools elsewhere:** `python -m tools.server` runs the MCP server for any MCP client (e.g. Claude Desktop).

> Research aid only. Not medical advice. Verify against the cited sources before making decisions.
