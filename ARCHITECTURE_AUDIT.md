# CoSolve Architecture Audit

> Static analysis report. No code was changed during this audit.
> Date: 2026-03-06

---

## Refactoring Status

- Priority 1: Completed — 2026-03-07
  - Deleted `ConversationHandler` (stub class + empty directory)
  - Deleted `IntentReflectionNode` (retired node file)
  - Removed `IntentReflectionOutput` model + `intent_reflection_llm` dead variable
  - Removed `classification_low_confidence` from `IncidentGraphState` TypedDict
  - Fixed duplicate `reindex_case` in `entry_handler.py` (kept second definition with better error handling)
  - Removed `KPIMetrics` and `KPIAnalyticsTool` backward-compat aliases
  - Removed `print()` debug statements from `routes.py`
  - NOTE: `similarity_escalated` and `strategy_escalated` are NOT dead — they are read by `escalation_controller.py` and `model_policy.py`. Audit was incorrect on these.
- Priority 2: Completed — 2026-03-07
  - `KnowledgeFormatter` → module-level singleton in `knowledge_formatter.py`
  - `_normalize_action` → consolidated to `backend/utils/text.py`
  - `StrategyReflectionNode` → removed misleading `BaseReflectionNode` inheritance
  - `/llm/stats` endpoint → marked DEPRECATED with TODO comment (UI still references it)
- Priority 3: Completed — 2026-03-07
  - `clarifying_question` → no change needed (working as designed: node writes, entry_handler reads from graph result)
  - `BaseReflectionNode.run()` → made `case_id` parameter optional (default `""`)
  - Debug endpoints → gated behind `COSOLVE_ENV=development` environment flag

---

## Section 1 — Class Inventory

### Infrastructure & Configuration

| Class | File | Inherits | Purpose | Status |
|-------|------|----------|---------|--------|
| Settings | backend/config.py:9 | BaseSettings | Env-var configuration for all Azure endpoints, LLM deployments, retrieval params | ✅ Core |
| BackendContainer | backend/app.py:63 | — | DI container wiring all infrastructure, ingestion, workflow, and node instances | ✅ Core |
| BackendApp | backend/app.py:249 | — | FastAPI app wrapper with OTEL tracing and CORS | ✅ Core |
| ModelPolicy | backend/ai/model_policy.py:6 | — | Adaptive base vs premium model selection | ✅ Core |
| EscalationController | backend/ai/escalation_controller.py:4 | — | Determines whether reflection triggers escalation | ✅ Core |

### Storage & Search

| Class | File | Inherits | Purpose | Status |
|-------|------|----------|---------|--------|
| BlobStorageClient | backend/infra/blob_storage.py:9 | — | Azure Blob Storage abstraction | ✅ Core |
| CaseRepository | backend/infra/blob_storage.py:94 | — | Write/create case documents in blob | ✅ Core |
| CaseReadRepository | backend/infra/blob_storage.py:143 | — | Read-only case retrieval from blob | ✅ Core |
| EmbeddingClient | backend/infra/embeddings.py:13 | — | Azure OpenAI embeddings | ✅ Core |
| CaseSearchClient | backend/infra/case_search_client.py:13 | — | Hybrid search over case index | ✅ Core |
| EvidenceSearchClient | backend/infra/evidence_search_client.py:9 | — | Hybrid search over evidence index | ✅ Core |
| KnowledgeSearchClient | backend/infra/knowledge_search_client.py:11 | — | Hybrid search over knowledge index | ✅ Core |
| HybridRetriever | backend/retrieval/hybrid_retriever.py:20 | — | Unified retrieval facade combining all 3 search clients | ✅ Core |

### Search Index Builders

| Class | File | Inherits | Purpose | Status |
|-------|------|----------|---------|--------|
| CaseSearchIndex | backend/ingestion/case_ingestion.py:25 | — | Azure Search index adapter for cases | ✅ Core |
| EvidenceSearchIndex | backend/ingestion/evidence_ingestion.py:16 | — | Azure Search index adapter for evidence | ✅ Core |
| KnowledgeSearchIndex | backend/ingestion/knowledge_ingestion.py:22 | — | Azure Search index adapter for knowledge | ✅ Core |

### Ingestion Services

| Class | File | Inherits | Purpose | Status |
|-------|------|----------|---------|--------|
| CaseEntryService | backend/ingestion/case_ingestion.py:78 | — | Case lifecycle (create, patch, close) | ✅ Core |
| CaseIngestionService | backend/ingestion/case_ingestion.py:221 | — | Index case documents into Azure Search | ✅ Core |
| EvidenceIngestionService | backend/ingestion/evidence_ingestion.py:46 | — | Ingest evidence files into index | ✅ Core |
| KnowledgeIngestionService | backend/ingestion/knowledge_ingestion.py:49 | — | Ingest knowledge docs (PDF/DOCX) into index | ✅ Core |

### State & Models

| Class | File | Inherits | Purpose | Status |
|-------|------|----------|---------|--------|
| IncidentStateModel | backend/state/incident_state.py:9 | BaseModel | Core incident state schema | ✅ Core |
| IncidentState | backend/state/incident_state.py:17 | BaseModel | Normalized incident with `from_payload()` factory | ✅ Core |
| LegacyCaseHeader | backend/state/incident_state.py:76 | BaseModel | Legacy case header fields | ✅ Core |
| LegacyCaseMeta | backend/state/incident_state.py:83 | BaseModel | Legacy metadata (version, timestamps) | ✅ Core |
| LegacyCaseAI | backend/state/incident_state.py:89 | BaseModel | Legacy AI summary block | ✅ Core |
| LegacyCaseModel | backend/state/incident_state.py:96 | BaseModel | Full legacy case document schema | ✅ Core |
| IncidentFactory | backend/state/incident_state.py:104 | — | Static factory for empty incident documents | ✅ Core |
| IncidentStateAdapter | backend/state/incident_state.py:125 | — | Static adapter for legacy-to-canonical normalization | ✅ Core |
| ConversationHandler | backend/conversation/conversation_handler.py:4 | — | Placeholder stub — no implementation | ❌ Dead |

### API Layer

| Class | File | Inherits | Purpose | Status |
|-------|------|----------|---------|--------|
| ApiRoutes | backend/api/routes.py:35 | — | Central route handler for all HTTP endpoints | ✅ Core |
| CaseSearchRequest | backend/api/routes.py:24 | BaseModel | Search request schema | ✅ Core |
| SuggestionsRequest | backend/api/routes.py:30 | BaseModel | Suggestion generation request | ✅ Core |
| EntryEnvelope | backend/entry/entry_handler.py:37 | BaseModel | Unified request envelope | ✅ Core |
| EntryResponseEnvelope | backend/entry/entry_handler.py:45 | BaseModel | Unified response envelope | ✅ Core |
| SuggestionItem | backend/entry/entry_handler.py:25 | BaseModel | Single suggestion label+question | ✅ Core |
| SuggestionsLLMResponse | backend/entry/entry_handler.py:30 | BaseModel | LLM-generated suggestion list | ✅ Core |
| EntryHandler | backend/entry/entry_handler.py:52 | — | Orchestrator for case/evidence/knowledge/reasoning flows | ✅ Core |

### Workflow Nodes

| Class | File | Inherits | Purpose | Status |
|-------|------|----------|---------|--------|
| StartNode | backend/workflow/nodes/start_node.py:4 | — | Entry point (no-op) | ✅ Core |
| ContextNode | backend/workflow/nodes/context_node.py:9 | — | Loads case context from blob | ✅ Core |
| IntentClassificationNode | backend/workflow/nodes/intent_classification_node.py:9 | — | LLM-based intent + scope classification | ✅ Core |
| QuestionReadinessNode | backend/workflow/nodes/question_readiness_node.py:12 | — | Validates question is answerable | ✅ Core |
| RouterNode | backend/workflow/nodes/router_node.py:6 | — | Routes to agent by classified intent | ✅ Core |
| OperationalNode | backend/workflow/nodes/operational_node.py:25 | — | Day-to-day maintenance reasoning | ✅ Core |
| SimilarityNode | backend/workflow/nodes/similarity_node.py:18 | — | Cross-reference closed cases | ✅ Core |
| StrategyNode | backend/workflow/nodes/strategy_node.py:18 | — | Portfolio/systemic reasoning | ✅ Core |
| KPINode | backend/workflow/nodes/kpi_node.py:10 | — | Metrics computation | ✅ Core |
| BaseReflectionNode | backend/workflow/nodes/base_reflection_node.py:16 | — | Shared assess-score-regenerate-build template | ⚠️ Simplify |
| OperationalReflectionNode | backend/workflow/nodes/operational_reflection_node.py:17 | BaseReflectionNode | Quality audit for operational drafts | ✅ Core |
| SimilarityReflectionNode | backend/workflow/nodes/similarity_reflection_node.py:13 | BaseReflectionNode | Quality audit for similarity drafts | ✅ Core |
| StrategyReflectionNode | backend/workflow/nodes/strategy_reflection_node.py:19 | BaseReflectionNode | Quality audit for strategy drafts | ⚠️ Simplify |
| KPIReflectionNode | backend/workflow/nodes/kpi_reflection_node.py:54 | — | KPI interpretation + semantic audit | ✅ Core |
| OperationalEscalationNode | backend/workflow/nodes/operational_escalation_node.py:10 | — | Re-runs operational with premium model | ✅ Core |
| StrategyEscalationNode | backend/workflow/nodes/strategy_escalation_node.py:10 | — | Re-runs strategy with premium model | ✅ Core |
| ResponseFormatterNode | backend/workflow/nodes/response_formatter_node.py:17 | — | Assembles final response payload | ✅ Core |
| EndNode | backend/workflow/nodes/end_node.py:6 | — | Terminal node (pass-through) | ✅ Core |
| IntentReflectionNode | backend/workflow/nodes/intent_reflection_node.py:26 | — | Retired — kept for reference only | ❌ Dead |

### Workflow Support

| Class | File | Inherits | Purpose | Status |
|-------|------|----------|---------|--------|
| KnowledgeFormatter | backend/workflow/services/knowledge_formatter.py:6 | — | Formats knowledge refs for LLM prompts | ⚠️ Simplify |
| _RawClassification | backend/workflow/nodes/intent_coercion.py:18 | BaseModel | Lenient LLM output schema for intent parsing | ✅ Core |
| IntentReflectionAssessment | backend/workflow/nodes/intent_reflection_node.py:18 | BaseModel | Part of retired IntentReflectionNode | ❌ Dead |

### Workflow Models (28 Pydantic models in backend/workflow/models.py)

All ✅ Core. Key models: `IntentClassificationResult`, `OperationalPayload`, `SimilarityPayload`, `StrategyPayload`, `KPIResult`, `FinalResponsePayload`, and their reflection assessment/output counterparts.

**Alias:** `KPIMetrics = KPIResult` (line 99) — backward-compat alias.
**Alias:** `KPIAnalyticsTool = KPITool` (backend/tools/kpi_tool.py:551) — backward-compat alias.

### Tools

| Class | File | Inherits | Purpose | Status |
|-------|------|----------|---------|--------|
| KPITool | backend/tools/kpi_tool.py:29 | — | Multi-scope KPI computation (global/country/case) | ✅ Core |
| UnifiedIncidentGraph | backend/workflow/unified_incident_graph.py:78 | — | LangGraph orchestrator with 17 nodes | ✅ Core |
| IncidentGraphState | backend/workflow/unified_incident_graph.py:45 | TypedDict | LangGraph state schema | ✅ Core |

---

## Section 2 — Object Instantiation Hotspots

### Instantiated with same arguments more than once

| Class | Occurrences | Fix |
|-------|-------------|-----|
| KnowledgeFormatter | 3x — OperationalNode, SimilarityNode, StrategyNode (each `self._formatter = KnowledgeFormatter()`) | Instantiate once in BackendContainer and inject |

### All other classes

All infrastructure, search, ingestion, and node classes follow the correct singleton pattern via `BackendContainer.__init__()`. Each is instantiated exactly once and injected into dependents.

### Per-request instantiation

None found. All graph invocations use pre-built node instances. The `get_llm()` factory uses `@lru_cache(maxsize=16)` for LLM client reuse.

### Instantiated inside loops

None found.

---

## Section 3 — State Object Audit

The `IncidentGraphState` TypedDict has 25 fields. Analysis:

### Dead fields (written but never read, or never written)

| Field | Issue |
|-------|-------|
| `similarity_escalated` | Written by `start_node` (initialized to `False`) but never read by any node or routing function |
| `strategy_escalated` | Written by `strategy_escalation_node` but never read by any node or routing function |
| `classification_low_confidence` | Defined in TypedDict but only checked in `entry_handler.py:319` (outside graph). Never written by any graph node since IntentReflectionNode was retired |
| `clarifying_question` | Written by `question_readiness_node` but only read in `entry_handler.py:327` (outside graph). Inside the graph it's never consumed |

### Shared writes (same field written by multiple nodes)

| Field | Writers | Risk |
|-------|---------|------|
| `_last_node` | Every node via `_traced_node()`, plus `invoke()` | Low — logging/tracing only |
| `trace_id` | `invoke()` and `_traced_node()` | Low — propagation only |
| `operational_draft` | `operational_node` and `operational_escalation_node` | Intentional — escalation overwrites draft |
| `strategy_draft` | `strategy_node` and `strategy_escalation_node` | Intentional — escalation overwrites draft |

### Complex nested objects where flat values would suffice

| Field | Type | Assessment |
|-------|------|------------|
| `case_context` | `dict` (full case document) | Required — multiple nodes extract different sub-fields |
| `classification` | `IntentClassificationResult` (3 fields) | Appropriate granularity |

No over-nested state fields found.

---

## Section 4 — Function Duplication

### Duplicated function names across files

| Function | Files | Assessment |
|----------|-------|------------|
| `run` | Every node class | Expected — polymorphic interface. Not a duplication issue |
| `_normalize_action` | `entry_handler.py:588`, `routes.py:766` | Genuine duplication — identical logic. Extract to shared utility |
| `reindex_case` | `entry_handler.py:478` and `entry_handler.py:563` | Same method defined **twice** in the same class (lines 478 and 563). The second definition shadows the first. Bug |

### No other function name duplications found

Utility functions (`extract_suggestions`, `extract_similarity_suggestions`, `is_new_problem_question`, `format_d_states`, `normalize_d_states`) are unique to `node_parsing_utils.py`.

---

## Section 5 — LangChain Redundancy Check

### Old custom client references

| Pattern | Found | Assessment |
|---------|-------|------------|
| `LanguageModelClient` | 0 hits in backend/ | Clean — fully removed |
| `LoggedLanguageModelClient` | 0 hits in backend/ | Clean — fully removed |
| `language_model_client.py` | File deleted | Clean |
| `llm_logging_client.py` | File deleted | Clean |

### Token/usage references (legitimate)

| File | Lines | Context |
|------|-------|---------|
| backend/api/routes.py:676-692 | `prompt_tokens`, `completion_tokens`, `total_tokens` | Reads from `llm_calls.jsonl` log for LLM stats aggregation |
| backend/entry/entry_handler.py:151-153 | Same token fields | Reads from same log file for LLM performance stats |

**Note:** These references read from `logs/llm_calls.jsonl` which was populated by the old `LoggedLanguageModelClient`. Since that client is now deleted, **no new data is being written to this log file**. The stats endpoints (`/llm/stats`, "show me llm performance stats") will only show historical data until this is addressed.

### Token tracking gap

Langfuse now tracks token usage automatically via the `CallbackHandler`. The JSONL-based `/llm/stats` endpoint and `_compute_llm_stats()` method in `EntryHandler` are now **orphaned infrastructure** — they read a log file that nothing writes to.

**Options:**
1. Remove `/llm/stats` and `_compute_llm_stats()` — let Langfuse dashboard be the single source of truth
2. Replace with Langfuse API queries to preserve the in-app stats panel

---

## Section 6 — Node Base Class Audit

### BaseReflectionNode (backend/workflow/nodes/base_reflection_node.py)

**Methods:**

| Method | Purpose | Used by children |
|--------|---------|-----------------|
| `__init__(llm_client, regeneration_llm_client, reflection_prompt, regeneration_prompt, assessment_model, score_fn, output_builder)` | Stores LLM clients + 5 callables | Operational, Similarity, Strategy (via `super().__init__()`) |
| `run(draft_text, question, case_id)` | Assess -> score -> conditionally regenerate -> build output | Operational, Similarity only. Strategy overrides completely |

**Findings:**

1. **StrategyReflectionNode violates LSP** — extends BaseReflectionNode but completely overrides `run()` without calling `super().run()`. The base class `_score` and `_build_output` callables are passed to `super().__init__()` but never invoked. StrategyReflectionNode should be a standalone class.

2. **KPIReflectionNode correctly does NOT extend BaseReflectionNode** — its 3-step pattern (generate -> audit -> regenerate -> verdict) is structurally different from the assess-score-regenerate template.

3. **Constructor boilerplate** — all 3 children pass hardcoded prompts, assessment models, and scoring functions to `super().__init__()`. This is unavoidable given each child's unique logic.

4. **`_current_draft` storage pattern** — both OperationalReflectionNode and SimilarityReflectionNode store a `_current_draft` instance variable in `run()` (set before, cleared in `finally`). Identical pattern but with different types (`OperationalPayload` vs `SimilarityPayload`).

5. **Dependency injection is correct** — nodes receive LLM clients via constructor. `get_llm()` factory caching makes this efficient. Constructor injection preserves testability.

---

## Section 7 — Refactoring Priority List

### PRIORITY 1 — Remove immediately (zero risk, zero value)

- **ConversationHandler** (`backend/conversation/conversation_handler.py`) — placeholder class, never imported or used
- **IntentReflectionNode** (`backend/workflow/nodes/intent_reflection_node.py`) — retired node, kept "for reference". Comments in `unified_incident_graph.py` explain retirement. Delete file
- **IntentReflectionAssessment** (`backend/workflow/nodes/intent_reflection_node.py:18`) — part of retired node
- **Dead state fields:**
  - `similarity_escalated` — remove from TypedDict, remove initialization in `start_node`
  - `strategy_escalated` — remove from TypedDict, remove write in `strategy_escalation`
  - `classification_low_confidence` — remove from TypedDict (only checked outside graph in `entry_handler.py:319`; that check can use `classification.confidence < threshold` instead)
- **Duplicate `reindex_case` method** in `entry_handler.py` — the method is defined twice (lines 478 and 563). Remove the first definition (lines 478-486); the second (lines 563-586) has better error handling
- **`KPIMetrics` alias** (`models.py:99`) — only `KPIResult` is used everywhere
- **`KPIAnalyticsTool` alias** (`kpi_tool.py:551`) — only `KPITool` is used in `app.py` imports

### PRIORITY 2 — Simplify (low risk, high value)

- **KnowledgeFormatter** — instantiated 3x with identical (empty) args. Instantiate once in `BackendContainer`, inject into OperationalNode, SimilarityNode, StrategyNode
- **`_normalize_action`** — duplicated in `entry_handler.py` and `routes.py`. Extract to a shared utility (e.g. `backend/utils.py`)
- **StrategyReflectionNode** — remove BaseReflectionNode inheritance. It overrides `run()` completely without calling `super()`. Make it a standalone class to eliminate misleading inheritance
- **`/llm/stats` endpoint + `_compute_llm_stats()`** — reads from `logs/llm_calls.jsonl` which is no longer written to (old custom client deleted). Either remove or rewire to Langfuse API

### PRIORITY 3 — Restructure (medium risk, architectural improvement)

- **`clarifying_question` state field** — currently written by `question_readiness_node` but only consumed by `entry_handler.py` (outside the graph). Consider moving the clarifying-question logic entirely outside the graph, or making the response formatter handle it
- **BaseReflectionNode `run()` signature** — children override with different signatures (`question + draft` vs `draft_text + question + case_id`). The base signature is misleading. Consider making it accept `**kwargs` or splitting into a protocol/interface
- **Debug endpoints** (`/cases/debug/*`, `/knowledge/debug/*`) — marked "temporary" in code comments. Remove or move behind an admin auth guard

### PRIORITY 4 — Defer (valid but not urgent)

- **`on_event("shutdown")` deprecation** — FastAPI warns this is deprecated in favor of lifespan events. Low urgency but will become a hard error in future FastAPI versions
- **`_MODEL_COSTS` dict in EntryHandler** — hardcoded cost rates for the old logging client. Only used by `_compute_llm_stats()`. Remove when stats endpoint is addressed
- **LegacyCase* models** — 4 Pydantic models for legacy case document format. Still needed for backward compatibility with seeded data. Defer until data migration is complete
- **`print()` statements** — `routes.py:617` and `routes.py:624` contain debug `print()` calls. Replace with `_logger.debug()`

---

*End of audit. No code was changed.*
