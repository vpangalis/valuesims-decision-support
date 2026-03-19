# UC02 — Operational Domain: Code Navigation Links

Companion to [uc02_operational_domain.mmd](./uc02_operational_domain.mmd).
Follow the sequence diagram step-by-step using the links below.

---

## STEP 1 — User → UI

| # | What | Link |
|---|------|------|
| 1 | User types question in AI textarea | [index.html:943](../../ui/index.html#L943) |
| 2 | Submit builds payload `{ intent, case_id, payload: { question, ... } }` | [cosolve-ui.js:2081](../../ui/cosolve-ui.js#L2081) |
| 3 | `fetch(${API_BASE}/entry/reasoning, { method:"POST", body: JSON.stringify(payload) })` | [cosolve-ui.js:2094](../../ui/cosolve-ui.js#L2094) |

---

## STEP 2 — UI → support_routes.py

| # | What | Link |
|---|------|------|
| 4 | `@router.post("/entry/reasoning")` — FastAPI matches URL | [support_routes.py:107](../../backend/gateway/api/support_routes.py#L107) |
| 5 | `handle_reasoning_entry(envelope: EntryEnvelope)` — JSON body parsed into Pydantic model | [support_routes.py:108](../../backend/gateway/api/support_routes.py#L108) |
| 6 | Guard: reject if `intent != "AI_REASONING"` | [support_routes.py:109](../../backend/gateway/api/support_routes.py#L109) |
| 7 | `_dispatch_entry_handler(envelope)` — wraps in HTTP error handling | [support_routes.py:82](../../backend/gateway/api/support_routes.py#L82) |
| 8 | Calls `entry_handler.handle_entry(envelope)` | [support_routes.py:84](../../backend/gateway/api/support_routes.py#L84) |

---

## STEP 3 — support_routes.py → entry_handler.py

| # | What | Link |
|---|------|------|
| 9 | `EntryEnvelope` Pydantic model — shape of the incoming JSON body | [entry_handler.py:31](../../backend/gateway/entry_handler.py#L31) |
| 10 | `handle_entry(envelope)` — reads `envelope.intent` and dispatches | [entry_handler.py:63](../../backend/gateway/entry_handler.py#L63) |
| 11 | `if intent == "AI_REASONING"` — branches to reasoning path | [entry_handler.py:67](../../backend/gateway/entry_handler.py#L67) |
| 12 | Calls `handle_ai_reasoning(envelope, self._unified_graph)` | [entry_handler.py:68](../../backend/gateway/entry_handler.py#L68) |

---

## STEP 4 — entry_handler.py → reasoning_handler.py

| # | What | Link |
|---|------|------|
| 13 | `handle_ai_reasoning(envelope, graph)` — reasoning pipeline entry point | [reasoning_handler.py:43](../../backend/gateway/reasoning_handler.py#L43) |
| 14 | Extract `question` from `envelope.payload` | [reasoning_handler.py:49](../../backend/gateway/reasoning_handler.py#L49) |
| 15 | Extract `case_id` from payload or envelope root | [reasoning_handler.py:50](../../backend/gateway/reasoning_handler.py#L50) |
| 16 | Guard: empty question → returns `usage` response immediately | [reasoning_handler.py:52](../../backend/gateway/reasoning_handler.py#L52) |
| 17 | Build `initial_state = { case_id, question }` — graph seed | [reasoning_handler.py:60](../../backend/gateway/reasoning_handler.py#L60) |
| 18 | **`graph.invoke(initial_state)` — RUNS ENTIRE PIPELINE (blocking call)** | [reasoning_handler.py:66](../../backend/gateway/reasoning_handler.py#L66) |

---

## STEP 5 — graph.py wiring

| # | What | Link |
|---|------|------|
| 19 | `build_graph()` — compiles entire node/edge topology at server start | [graph.py:34](../../backend/core/graph.py#L34) |
| 20 | `graph.set_entry_point("start_node")` | [graph.py:57](../../backend/core/graph.py#L57) |
| 21 | `graph.set_finish_point("end_node")` | [graph.py:58](../../backend/core/graph.py#L58) |
| 22 | Hard edge: `start_node` → `context_node` | [graph.py:61](../../backend/core/graph.py#L61) |
| 23 | Hard edge: `context_node` → `intent_classification_node` | [graph.py:62](../../backend/core/graph.py#L62) |
| 24 | Hard edge: `intent_classification_node` → `question_readiness_node` | [graph.py:63](../../backend/core/graph.py#L63) |
| 25 | Conditional: `question_readiness_node` → `READY`/`NOT_READY` | [graph.py:65](../../backend/core/graph.py#L65) |
| 26 | Conditional: `router_node` → `OPERATIONAL_CASE` → `operational_node` | [graph.py:74](../../backend/core/graph.py#L74) |
| 27 | Hard edge: `operational_node` → `operational_reflection_node` | [graph.py:85](../../backend/core/graph.py#L85) |
| 28 | Conditional: `operational_reflection_node` → `ESCALATE`/`CONTINUE` | [graph.py:86](../../backend/core/graph.py#L86) |
| 29 | Hard edge: `operational_escalation_node` → `operational_reflection_node` (loop back) | [graph.py:94](../../backend/core/graph.py#L94) |
| 30 | Hard edge: `response_formatter_node` → `end_node` | [graph.py:113](../../backend/core/graph.py#L113) |

---

## STEP 6 — Common nodes: start → router

| # | What | Link |
|---|------|------|
| 31 | `start_node(state)` — resets `operational_escalated`, `strategy_escalated` to False | [start_node.py:6](../../backend/reasoning/nodes/start_node.py#L6) |
| 32 | `context_node(state)` — loads case JSON from Azure Blob Storage | [context_node.py:23](../../backend/reasoning/nodes/context_node.py#L23) |
| 33 | `_get_case_entry_service()` — builds BlobStorageClient → CaseRepository → CaseEntryService | [context_node.py:13](../../backend/reasoning/nodes/context_node.py#L13) |
| 34 | `_detect_current_state(case_doc)` — detects current D-state (D1–D8) | [context_node.py:7](../../backend/reasoning/nodes/context_node.py#L7) |
| 35 | State updated: `case_context` + `current_d_state` added | [context_node.py:42](../../backend/reasoning/nodes/context_node.py#L42) |
| 36 | `intent_classification_node(state)` — LLM classifies intent + scope + confidence | [intent_classification_node.py:11](../../backend/reasoning/nodes/intent_classification_node.py#L11) |
| 37 | State updated: `classification: { intent, scope, confidence }` added | [intent_classification_node.py:11](../../backend/reasoning/nodes/intent_classification_node.py#L11) |
| 38 | `question_readiness_node(state)` — checks if question is clear enough | [question_readiness_node.py:18](../../backend/reasoning/nodes/question_readiness_node.py#L18) |
| 39 | Fast path: case loaded OR KPI/Strategy → `question_ready: True` immediately (no LLM) | [question_readiness_node.py:25](../../backend/reasoning/nodes/question_readiness_node.py#L25) |
| 40 | `route_question_readiness(state)` — returns `"READY"` or `"NOT_READY"` | [routing.py:15](../../backend/reasoning/routing.py#L15) |
| 41 | `router_node(state)` — reads `classification["intent"]`, sets `route` key | [router_node.py:6](../../backend/reasoning/nodes/router_node.py#L6) |
| 42 | `route_intent(state)` — returns `"OPERATIONAL_CASE"` → dispatches to operational_node | [routing.py:24](../../backend/reasoning/routing.py#L24) |

---

## STEP 7 — operational_node entry

| # | What | Link |
|---|------|------|
| 43 | `operational_node(state)` — wrapper, calls `_run_operational(state, model_name=None)` | [operational_node.py:31](../../backend/reasoning/nodes/operational_node.py#L31) |
| 44 | `_run_operational(state, model_name)` — core logic shared by node + escalation | [operational_node.py:36](../../backend/reasoning/nodes/operational_node.py#L36) |
| 45 | Read from state: `question`, `case_id`, `case_context`, `current_d_state`, `case_status` | [operational_node.py:38](../../backend/reasoning/nodes/operational_node.py#L38) |
| 46 | `get_llm("reasoning", 0.2)` — Azure OpenAI client via LLM factory | [operational_node.py:44](../../backend/reasoning/nodes/operational_node.py#L44) |

---

## STEP 8 — Knowledge search (all branches run this first)

| # | What | Link |
|---|------|------|
| 47 | `search_knowledge_base.invoke({ query, top_k:4, cosolve_phase })` | [operational_node.py:47](../../backend/reasoning/nodes/operational_node.py#L47) |
| 48 | `search_knowledge_base` `@tool` definition | [tools.py:271](../../backend/knowledge/tools.py#L271) |
| 49 | `hybrid_search_knowledge()` — calls knowledge search client | [knowledge_search_client.py:40](../../backend/knowledge/knowledge_search_client.py#L40) |
| 50 | `_get_knowledge_search_client()` — singleton for `knowledge_index_v2` | [tools.py:40](../../backend/knowledge/tools.py#L40) |
| 51 | Azure AI Search returns `List[Document]` → built into `knowledge_block` text | [operational_node.py:50](../../backend/reasoning/nodes/operational_node.py#L50) |

---

## STEP 9 — Branch A: New problem (no case loaded)

| # | What | Link |
|---|------|------|
| 52 | `is_new_problem_question(question, case_id)` — True if no case + new problem keywords | [operational_node.py:61](../../backend/reasoning/nodes/operational_node.py#L61) |
| 53 | Build `user_prompt` = question + knowledge block | [operational_node.py:62](../../backend/reasoning/nodes/operational_node.py#L62) |
| 54 | `llm.invoke([SystemMessage(OPERATIONAL_NEW_PROBLEM_SYSTEM_PROMPT), HumanMessage])` | [operational_node.py:66](../../backend/reasoning/nodes/operational_node.py#L66) |
| 55 | `extract_suggestions(response_text)` — parses `[WHAT TO EXPLORE NEXT]` | [operational_node.py:72](../../backend/reasoning/nodes/operational_node.py#L72) |
| 56 | Returns `{ "operational_draft": { current_state:"No case loaded", recommendations, suggestions } }` | [operational_node.py:73](../../backend/reasoning/nodes/operational_node.py#L73) |

---

## STEP 10 — Branch B: Closed case

| # | What | Link |
|---|------|------|
| 57 | `if case_status == "closed" and case_id` — entry condition | [operational_node.py:86](../../backend/reasoning/nodes/operational_node.py#L86) |
| 58 | `search_similar_cases.invoke({ query, current_case_id, country })` | [operational_node.py:87](../../backend/reasoning/nodes/operational_node.py#L87) |
| 59 | `search_similar_cases` `@tool` definition | [tools.py:76](../../backend/knowledge/tools.py#L76) |
| 60 | `hybrid_search_cases()` — case search client | [case_search_client.py:66](../../backend/knowledge/case_search_client.py#L66) |
| 61 | Azure AI Search → `case_index_v3` → returns `List[CaseSummary]` | [operational_node.py:87](../../backend/reasoning/nodes/operational_node.py#L87) |
| 62 | `search_evidence.invoke({ query, case_id })` — filtered by case_id | [operational_node.py:90](../../backend/reasoning/nodes/operational_node.py#L90) |
| 63 | `search_evidence` `@tool` definition | [tools.py:324](../../backend/knowledge/tools.py#L324) |
| 64 | `evidence_search_client` — singleton for `evidence_index_v1` | [evidence_search_client.py:36](../../backend/knowledge/evidence_search_client.py#L36) |
| 65 | Azure AI Search → `evidence_index_v1` → returns `List[EvidenceSummary]` | [operational_node.py:90](../../backend/reasoning/nodes/operational_node.py#L90) |
| 66 | `format_d_states(case_context)` — formats D1–D8 history text for LLM prompt | [operational_node.py:98](../../backend/reasoning/nodes/operational_node.py#L98) |
| 67 | Build `user_prompt`: closed case + history + cases + evidence + knowledge | [operational_node.py:94](../../backend/reasoning/nodes/operational_node.py#L94) |
| 68 | `llm.invoke([SystemMessage(OPERATIONAL_CLOSED_CASE_SYSTEM_PROMPT), HumanMessage])` | [operational_node.py:107](../../backend/reasoning/nodes/operational_node.py#L107) |
| 69 | `extract_suggestions(response_text)` | [operational_node.py:113](../../backend/reasoning/nodes/operational_node.py#L113) |
| 70 | Returns `{ "operational_draft": { current_state:"closed", recommendations, supporting_cases, referenced_evidence, suggestions } }` | [operational_node.py:114](../../backend/reasoning/nodes/operational_node.py#L114) |

---

## STEP 11 — Branch C: Open / active case

| # | What | Link |
|---|------|------|
| 71 | Falls through to active-case path (no closed match) | [operational_node.py:126](../../backend/reasoning/nodes/operational_node.py#L126) |
| 72 | `search_similar_cases.invoke(...)` — same tool as Branch B | [operational_node.py:129](../../backend/reasoning/nodes/operational_node.py#L129) |
| 73 | `search_evidence.invoke(...)` — same tool as Branch B | [operational_node.py:132](../../backend/reasoning/nodes/operational_node.py#L132) |
| 74 | `format_d_states(case_context)` | [operational_node.py:137](../../backend/reasoning/nodes/operational_node.py#L137) |
| 75 | Build `user_prompt`: active case + D-state + cases + evidence + knowledge | [operational_node.py:144](../../backend/reasoning/nodes/operational_node.py#L144) |
| 76 | `llm.invoke([SystemMessage(OPERATIONAL_SYSTEM_PROMPT), HumanMessage])` | [operational_node.py:159](../../backend/reasoning/nodes/operational_node.py#L159) |
| 77 | `extract_suggestions(response_text)` | [operational_node.py:166](../../backend/reasoning/nodes/operational_node.py#L166) |
| 78 | Returns `{ "operational_draft": { current_state, recommendations, supporting_cases, referenced_evidence, suggestions } }` | [operational_node.py:167](../../backend/reasoning/nodes/operational_node.py#L167) |

---

## STEP 12 — operational_reflection_node

| # | What | Link |
|---|------|------|
| 79 | `operational_reflection_node(state)` — assesses quality of `operational_draft` | [operational_reflection_node.py:27](../../backend/reasoning/nodes/operational_reflection_node.py#L27) |
| 80 | New-problem bypass: skip LLM if no case + new problem markers in draft | [operational_reflection_node.py:37](../../backend/reasoning/nodes/operational_reflection_node.py#L37) |
| 81 | `get_llm("reasoning", 0.0)` — deterministic (temp=0) | [operational_reflection_node.py:55](../../backend/reasoning/nodes/operational_reflection_node.py#L55) |
| 82 | `llm.with_structured_output(OperationalReflectionAssessment)` — forces structured JSON output | [operational_reflection_node.py:59](../../backend/reasoning/nodes/operational_reflection_node.py#L59) |
| 83 | Invoked with `OPERATIONAL_REFLECTION_SYSTEM_PROMPT` + draft text | [operational_reflection_node.py:59](../../backend/reasoning/nodes/operational_reflection_node.py#L59) |
| 84 | `_score(assessment)` — computes 0.0–1.0 quality score across 5 dimensions | [operational_reflection_node.py:64](../../backend/reasoning/nodes/operational_reflection_node.py#L64) |
| 85 | `_REGENERATION_THRESHOLD = 0.65` — minimum passing score | [operational_reflection_node.py:20](../../backend/reasoning/nodes/operational_reflection_node.py#L20) |
| 86 | If score < 0.65 → `regen_llm.invoke(OPERATIONAL_REGENERATION_SYSTEM_PROMPT)` | [operational_reflection_node.py:72](../../backend/reasoning/nodes/operational_reflection_node.py#L72) |
| 87 | `needs_escalation` flag — True if any of 5 assessment dimensions fail | [operational_reflection_node.py:77](../../backend/reasoning/nodes/operational_reflection_node.py#L77) |
| 88 | Returns `operational_result` + `operational_reflection` to state | [operational_reflection_node.py:86](../../backend/reasoning/nodes/operational_reflection_node.py#L86) |
| 89 | `route_operational_escalation(state)` — returns `"ESCALATE"` or `"CONTINUE"` | [routing.py:29](../../backend/reasoning/routing.py#L29) |

---

## STEP 13 — operational_escalation_node (only if ESCALATE)

| # | What | Link |
|---|------|------|
| 90 | `operational_escalation_node(state)` — re-runs with premium model | [operational_escalation_node.py:7](../../backend/reasoning/nodes/operational_escalation_node.py#L7) |
| 91 | Calls `_run_operational(state, model_name="reasoning")` — reuses full operational logic | [operational_escalation_node.py:9](../../backend/reasoning/nodes/operational_escalation_node.py#L9) |
| 92 | Sets `operational_escalated = True` | [operational_escalation_node.py:10](../../backend/reasoning/nodes/operational_escalation_node.py#L10) |
| 93 | Hard edge loops back to `operational_reflection_node` — reflection checks again | [graph.py:94](../../backend/core/graph.py#L94) |

---

## STEP 14 — response_formatter_node

| # | What | Link |
|---|------|------|
| 94 | `response_formatter_node(state)` — packages the final response | [response_formatter_node.py:9](../../backend/reasoning/nodes/response_formatter_node.py#L9) |
| 95 | Reads `classification["intent"]` — decides which result key to pick | [response_formatter_node.py:15](../../backend/reasoning/nodes/response_formatter_node.py#L15) |
| 96 | `intent == "OPERATIONAL_CASE"` → uses `state["operational_result"]` | [response_formatter_node.py:16](../../backend/reasoning/nodes/response_formatter_node.py#L16) |
| 97 | Returns `{ "final_response": { timestamp, classification, result: operational_result } }` | [response_formatter_node.py:25](../../backend/reasoning/nodes/response_formatter_node.py#L25) |
| 98 | Hard edge → `end_node` → graph finishes | [graph.py:113](../../backend/core/graph.py#L113) |

---

## STEP 15 — Back to reasoning_handler.py: response gates

| # | What | Link |
|---|------|------|
| 99 | `graph.invoke()` returns full `graph_result` state dict | [reasoning_handler.py:66](../../backend/gateway/reasoning_handler.py#L66) |
| 100 | Gate 1: `classification_low_confidence` → `build_clarifying_response()` | [reasoning_handler.py:71](../../backend/gateway/reasoning_handler.py#L71) |
| 101 | Gate 2: `question_ready == False` → `build_clarifying_question_response()` | [reasoning_handler.py:77](../../backend/gateway/reasoning_handler.py#L77) |
| 102 | Gate 3 (success): `graph_result.get("final_response")` | [reasoning_handler.py:82](../../backend/gateway/reasoning_handler.py#L82) |
| 103 | `build_clarifying_response()` — fallback with 4 suggestion chips | [reasoning_handler.py:90](../../backend/gateway/reasoning_handler.py#L90) |

---

## STEP 16 — EntryResponseEnvelope → UI

| # | What | Link |
|---|------|------|
| 104 | Build `EntryResponseEnvelope(intent, status:"accepted", data: final_response)` | [reasoning_handler.py:83](../../backend/gateway/reasoning_handler.py#L83) |
| 105 | `EntryResponseEnvelope` Pydantic model: `{ intent, status, data, errors }` | [entry_handler.py:39](../../backend/gateway/entry_handler.py#L39) |
| 106 | FastAPI auto-serializes to JSON — returned to browser | [support_routes.py:111](../../backend/gateway/api/support_routes.py#L111) |
| 107 | `fetch()` resolves in browser | [cosolve-ui.js:2094](../../ui/cosolve-ui.js#L2094) |
| 108 | `const data = await res.json()` — parse response | [cosolve-ui.js:2100](../../ui/cosolve-ui.js#L2100) |
| 109 | AI panel rendered: answer text + suggestion chips displayed | [cosolve-ui.js:2109](../../ui/cosolve-ui.js#L2109) |
