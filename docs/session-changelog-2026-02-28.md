# CoSolve Session Changelog — 2026-02-28

**Branch:** architecture-refactor  
**Commits this session:** d3ab783 → db0860e + subsequent

---

## Bug Fixes

| Commit | Description |
|--------|-------------|
| `d3ab783` | QuestionReadinessNode OVERRIDE RULE: case_loaded=true always returns ready for operational/similarity/strategy/KPI intents |
| `ec64c88` | similarity node case_status injection fix; strategy citation placeholder artifact removed |
| `ec22160` | WHAT THIS REVEALS renders as separate styled card; strategy citations apply to all sections |
| `6252de4` | strategy SYSTEMIC PATTERNS citation format with inline example; (EMERGING) label format fixed |
| `58a1e5d` | sub-bullet spacing: separate ul.sub-bullet-list from top-level bullets |
| `d93726a` | sub-bullet detection uses content pattern not indentation |
| `8816bb0` | sub-bullet items correctly wrapped in ul and styled as compact list |
| `46bdaa7` | global KPI scope renders bar_chart when country_ranking is populated |
| `a75068c` | KPI gauge uses retrospective language and closed date for closed cases |
| `bc8886a` | AI Reasoning panel resets correctly on new case load and clear |
| `52f33cf` | portfolio status questions excluded from OPERATIONAL_CASE intent |
| `104aa88` | KPI and strategy intents always ready regardless of case_loaded |
| `64fa41f` | isClosed reads status from caseContext.case.status |
| `693b00b` | intent reflection node coerces non-enum values before model_validate |
| `4694e50` | patch vienna→Austria/Vienna in search index |
| `0f36391` | API_BASE port updates |
| `8330710` | strategy CURRENT STATE uses plain stage names and lists case IDs per stage |

---

## Refactoring

| Commit | Description |
|--------|-------------|
| `db0860e` | shared intent coercion module; first-pass classifier uses RawClassification; @staticmethod violations resolved |

---

## KPI Routing

- `46bdaa7` — bar_chart render_hint when country_ranking populated
- `52f33cf` — KPI_ANALYSIS examples extended with case-specific timing questions
- `693b00b` + `db0860e` — intent coercion prevents ValidationError on free-form LLM responses

---

## Port History (development session)

Started on **8005** → moved to **8007** → **8008** → **8009** → **8010**

**Root cause:** Sonnet was starting uvicorn, creating port conflicts.  
**Rule established:** Only Vassilis starts uvicorn. Sonnet never starts the backend.

---

## Test Suite

**52/52 passing** at session close

---

## Known Issues / Next Session

- **"Vienna" still appears as separate bar chart entry** — additional cases with city stored as country field; need data audit
- **"Unknown" country** — 3 null-country cases; deferred to data audit
- **Greece 44 closed cases anomaly** — test data noise; needs audit
- **Active case portfolio listing** — missing feature; no node returns case list by stage/status
- `@staticmethod` on `_coerce_intent`, `_coerce_scope` in `intent_reflection_node.py` — resolved in `db0860e` via shared module
- **pycache stale bytecode** — wipe pycache before every hard restart

---

## Architectural Rules Reinforced

1. No `@staticmethod` unless called by name from outside the class with no instance
2. No standalone functions outside classes except pure utilities in shared modules called by multiple unrelated classes
3. Sonnet never starts uvicorn
4. No radical infrastructure changes without full audit first
