# API_CONTRACT.md — CoSolve UI/Backend Envelope

This document defines the exact shape of every message that crosses
the boundary between the UI and the backend. Nothing else crosses this boundary.

Enforced by `CoSolveRequest` and `CoSolveResponse` in `backend/api/schemas.py`.

---

## Principle

```
UI  →  CoSolveRequest  →  [routes.py translation]  →  IncidentGraphState  →  graph
UI  ←  CoSolveResponse ←  [routes.py translation]  ←  IncidentGraphState  ←  graph
```

`IncidentGraphState` is internal — it never reaches the UI.
`CoSolveRequest` / `CoSolveResponse` are external — they never enter the graph.
`routes.py` is the only place where translation happens.

---

## REQUEST — UI → Backend

**Endpoint:** `POST /api/ask`

**Shape:**
```json
{
    "question": "Have we seen pantograph failures before?",
    "case_id": "TRM-20250310-0001",
    "session_id": "abc123"
}
```

**Field definitions:**

| Field | Type | Required | Description |
|---|---|---|---|
| `question` | string | yes | The user's natural language question |
| `case_id` | string | no | Currently loaded case ID. Null if no case loaded |
| `session_id` | string | no | UI session identifier for grouping traces in LangSmith |

**Rules:**
- UI must always send `question`
- UI sends `case_id` only when a case is loaded in the Case Board
- UI generates `session_id` once per browser session and reuses it
- No other fields are accepted — backend will reject unknown fields

---

## RESPONSE — Backend → UI

**Shape:**
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

**Field definitions:**

| Field | Type | Always present | Description |
|---|---|---|---|
| `answer` | string | yes | The main AI-generated response text |
| `intent` | string | yes | Classified intent: `OPERATIONAL_CASE`, `SIMILARITY_SEARCH`, `STRATEGY_ANALYSIS`, `KPI_ANALYSIS` |
| `sources` | array | yes (may be empty) | Cases or documents used to generate the answer |
| `sources[].case_id` | string | yes | Case or document identifier |
| `sources[].title` | string | yes | Human-readable title |
| `sources[].relevance` | float | no | Relevance score 0.0–1.0 |
| `suggested_questions` | object | no | Follow-up questions split by audience |
| `suggested_questions.ask_your_team` | array | yes | Questions for the human team |
| `suggested_questions.ask_cosolve` | array | yes | Questions to ask CoSolve next |
| `warning` | string | no | Non-fatal warning shown as banner in UI. Null if no warning |

---

## ERROR RESPONSES

**Validation error (422):**
```json
{
    "detail": [{"loc": ["body", "question"], "msg": "field required", "type": "value_error.missing"}]
}
```

**Server error (500):**
```json
{
    "detail": "Internal server error"
}
```

**No case loaded — not an error, communicated via `warning`:**
```json
{
    "answer": "No case is currently loaded...",
    "intent": "OPERATIONAL_CASE",
    "sources": [],
    "suggested_questions": null,
    "warning": "No case loaded. Please open a case in the Case Board."
}
```

---

## WHAT THE UI IS RESPONSIBLE FOR

- Generating and persisting `session_id` for the browser session
- Sending `case_id` when a case is loaded, null when not
- Displaying `warning` as a banner when non-null
- Rendering `sources` as reference links
- Rendering `suggested_questions.ask_your_team` and `ask_cosolve` as chips
- Handling 422 and 500 responses gracefully

## WHAT THE BACKEND IS RESPONSIBLE FOR

- Validating `CoSolveRequest` shape — reject unknown fields
- Always returning `CoSolveResponse` shape — never return raw state fields
- Setting `warning` instead of throwing an error for expected no-case scenarios
- Always populating `intent` — never null
- Always returning `sources` array — empty array if no sources, never null

---

## VERSION

Contract version: `1.0`
Last updated: 2026-03-08
Any change to this contract requires updating both `schemas.py` and this document together.
