# CLAUDE.md — CoSolve by Valuesims

> Project context for Claude Code. Read this before touching any file.

---

## What This Project Is

**CoSolve** is an AI-powered industrial decision support system with the tagline *"Collaborative problem solving, powered by AI."*

It serves railway/tram operations teams analysing maintenance and procurement issues — helping them navigate complex technical problems through structured case management and AI-guided reasoning. The platform combines structured **8D methodology workflows** with intelligent knowledge surfacing from technical documentation (NSK Bearings manuals, Knorr-Bremse Quality Assurance Agreements, SAP procurement processes).

---

## Project Structure

```
valuesims-decision-support/   ← root (CLAUDE.md lives here)
├── CLAUDE.md
├── .env                      ← environment variables (always load with override=True)
├── .gitignore
├── .github/
├── .venv/
├── .vscode/
├── ARTIFACTS/                ← build/output artefacts
├── backend/                  ← FastAPI app, LangGraph nodes, Azure integrations
├── docs/                     ← project documentation
├── logs/                     ← runtime logs
├── scripts/                  ← utility scripts
├── tests/                    ← test suite
├── ui/                       ← vanilla JS frontend (three-panel layout)
├── generate_alignment_report.py
├── generate_project_docs.py
├── seed_50_cases.py          ← seeds case data into Azure Blob Storage & AI Search
├── requirements.txt
├── pytest.ini
├── run1_out … run4_out       ← test run output logs
├── runA_out … runC_out       ← test run output logs
├── start.bat                 ← Windows start script
└── start.ps1                 ← PowerShell start script
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI |
| AI Workflow | LangGraph (multi-node agentic pipeline) |
| Search | Azure AI Search — 3 indexes: `cases`, `evidence`, `knowledge_documents` |
| LLM | Azure OpenAI (Foundry deployment keys, **not** general resource keys) |
| Storage | Azure Blob Storage |
| Frontend | Vanilla JavaScript (single-page, three-panel layout) |
| Doc Processing | python-docx, PyPDF2, pypdf, pdfplumber |

---

## Architecture Overview

### Three-Panel UI
- **Left panel** — Documents & Search (accordion: opening one section collapses others)
- **Centre panel** — CoSolve Case Board (structured case workflows)
- **Right panel** — AI Reasoning (LangGraph pipeline output with citation chips)

### LangGraph Workflow
User questions are routed through a classifier to specialised reasoning nodes:

| Node | Purpose |
|---|---|
| `operational` | Day-to-day maintenance questions |
| `similarity` | Cross-references closed cases for precedents |
| `strategy` | Portfolio and systemic questions |
| `KPI` | Metrics and performance queries |

Each node uses a **three-pass internal sequence**:
1. Read case history sequentially
2. Cross-reference closed cases for precedents
3. Provide structured recommendations with citations

**Citation format:** `Per [Document Name]: [relevant point]`

Every AI response ends with **clickable suggestion chips** that guide users between the four reasoning agents.

### Knowledge Document Infrastructure
- Documents are chunked (~12,000 chars), indexed, and retrieved with proper citation formatting
- Three-stage PDF extraction fallback: PyPDF2 → pypdf → pdfplumber
- Scanned/image-only PDFs handled gracefully

---

## Current State

- ✅ Knowledge document infrastructure fully operational (chunking, indexing, UI management)
- ✅ Knowledge retrieval wired into all reasoning nodes (operational, similarity, strategy)
- ✅ Conversation history, dynamic suggestion generation, structured HTML rendering
- ✅ Three sample railway/tram industry cases seeded into Azure Blob Storage & AI Search
- ✅ Left panel accordion behaviour
- ✅ Clickable file links for knowledge citations → `/knowledge/file/{filename}` endpoint
- ✅ Operational and similarity nodes: ~15s response time, single LLM call
- 🔄 Strategy node: pending design decisions (data source selection, retrieval triggers, scope filtering)

---

## Commit Workflow (end of every session)

Before every commit, run these steps in order:

1. Read `docs/architecture.mmd`
2. Read all Python files in `backend/` and all JavaScript files in `ui/`
3. Compare the diagram against the actual code
4. Update only the parts that have changed — new/removed classes, renamed methods, new routes, new LangGraph nodes, changed connections
5. Keep existing structure and styling intact
6. Save back to `docs/architecture.mmd`
7. Then commit everything together with a precise commit message

---

## Key Architectural Rules — NO-GO LIST

> These apply to every prompt and every change. Non-negotiable.

1. **Audit first, change second.** Every prompt must be two-stage: (1) read-and-report only, (2) targeted change with explicit restrictions.
2. **No standalone / static functions.** All functions must belong to existing classes or closures.
3. **No deleting tested code.** Major deletions are prohibited. If something must be removed, confirm explicitly first.
4. **Minimum footprint.** Changes must be as small as possible. Do not refactor working code.
5. **No 8D methodology jargon** (D1, D2, etc.) in user-facing text. Use plain language only.
6. **Environment variables** — always use `override=True` in `load_dotenv()`. Windows system variables shadow `.env` values.
7. **Azure OpenAI** — use Foundry deployment keys, not general resource keys.

---

## 4 Post-Change Checks (run after every edit)

1. **Does the FastAPI docs interface (`/docs`) still load and accept requests?**
2. **Does the live UI render without JS console errors?**
3. **Does the changed node still return properly cited responses?**
4. **Are all existing suggestion chips still generated and clickable?**

---

## Debugging Approach

- Test at every stack layer: FastAPI `/docs` first, then live UI
- Use browser console tests and defensive coding
- Fresh DOM queries after dynamic renders
- Event delegation for dynamically inserted elements
- Validate fixes methodically before moving on

---

## Domain Context

**Key stakeholders:** Railway maintenance teams dealing with:
- Bearing failures
- Supplier specification errors
- Incoming goods inspection issues

**Success criteria:** Surface relevant precedents and technical documentation *before* users need to read lengthy manuals, while providing intelligent conversation flows that guide users toward logical next questions.

**Upcoming knowledge base additions:**
- NSK Bearings documentation
- SAP procurement guides
- 8D corrective action procedures

---

## Visual / UX Direction

- Business-like interface with panel differentiation via subtle background tints
- Improved typography and comprehensive CoSolve branding
- AI Reasoning panel: document filenames as clickable links
- No emojis, no consumer-app aesthetics

---

*Last updated from conversation memory — March 2026.*
