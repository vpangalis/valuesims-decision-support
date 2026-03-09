# API_CONTRACT.md — CoSolve UI/Backend Envelope
# Version: 3.0 — 2026-03-09
# Changes from v2.0: version bump only, contract unchanged

---

## Principle

```
UI → CoSolveRequest → [routes.py] → IncidentGraphState → graph
UI ← CoSolveResponse ← [routes.py] ← IncidentGraphState ← graph
```

IncidentGraphState is internal — never reaches the UI.
CoSolveRequest/CoSolveResponse are external — never enter the graph.
routes.py is the only translation point.

---

## REQUEST — UI → Backend

Endpoint: POST /api/ask

```json
{
    "question": "Have we seen pantograph failures before?",
    "case_id": "TRM-20250310-0001",
    "session_id": "abc123"
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| question | string | yes | User's natural language question |
| case_id | string | no | Currently loaded case ID. Null if no case loaded |
| session_id | string | no | UI session ID for LangSmith trace grouping |

Rules:
- UI always sends question
- UI sends case_id only when a case is loaded in the Case Board
- UI generates session_id once per browser session and reuses it
- Unknown fields are rejected (422)

---

## RESPONSE — Backend → UI

```json
{
    "answer": "Yes, pantograph failures have been recorded in 3 previous cases...",
    "intent": "SIMILARITY_SEARCH",
    "sources": [
        {
            "case_id": "TRM-20230318-0003",
            "title": "Pantograph wear at Kifisia Depot",
            "relevance": 0.91
        }
    ],
    "suggested_questions": {
        "ask_your_team": [
            "What maintenance was performed before this failure?",
            "Which technician signed off the last inspection?"
        ],
        "ask_cosolve": [
            "What are the typical root causes of pantograph wear?",
            "Which depots have the highest pantograph failure rate?"
        ]
    },
    "warning": null
}
```

| Field | Type | Always present | Description |
|---|---|---|---|
| answer | string | yes | Main AI-generated response |
| intent | string | yes | OPERATIONAL_CASE, SIMILARITY_SEARCH, STRATEGY_ANALYSIS, KPI_ANALYSIS |
| sources | array | yes (may be empty) | Cases or documents used to generate the answer |
| sources[].case_id | string | yes | Case or document identifier |
| sources[].title | string | yes | Human-readable title |
| sources[].relevance | float | no | Relevance score 0.0–1.0 |
| suggested_questions | object | no | Follow-up questions split by audience |
| suggested_questions.ask_your_team | array | yes if present | Questions for the human team |
| suggested_questions.ask_cosolve | array | yes if present | Questions to ask CoSolve next |
| warning | string | no | Non-fatal warning shown as banner in UI. Null if no warning |

---

## ERRORS

422 — Validation error (missing required field):
```json
{"detail": [{"loc": ["body", "question"], "msg": "field required"}]}
```

500 — Server error:
```json
{"detail": "Internal server error"}
```

No case loaded — NOT an error, communicated via warning field:
```json
{
    "answer": "No case is currently loaded...",
    "intent": "OPERATIONAL_CASE",
    "sources": [],
    "warning": "No case loaded. Please open a case in the Case Board."
}
```

---

## RESPONSIBILITIES

UI is responsible for:
- Generating and persisting session_id for the browser session
- Sending case_id when loaded, null when not
- Displaying warning as a banner when non-null
- Rendering sources as reference links
- Rendering suggested_questions.ask_your_team and ask_cosolve as chips
- Handling 422 and 500 gracefully

Backend is responsible for:
- Validating CoSolveRequest — reject unknown fields
- Always returning CoSolveResponse shape — never raw state fields
- Setting warning instead of throwing for expected no-case scenarios
- Always populating intent — never null
- Always returning sources array — empty if no sources, never null

---

## VERSION CONTROL

Contract version: 3.0
Any change to this contract requires updating BOTH schemas.py AND this document.
Never change one without the other.
