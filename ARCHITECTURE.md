# ARCHITECTURE.md — CoSolve Structural Decisions

---

## Guiding Principle

CoSolve is a LangGraph application. LangGraph IS the architecture.
The graph, state, tools, and runnables replace all custom scaffolding.
Do not fight the framework — use it.

---

## Directory Structure

```
backend/
    state.py                    ← ONE file, ONE TypedDict: IncidentGraphState
    prompts.py                  ← ALL prompts in one place, as constants
    tools.py                    ← ALL @tool functions, retriever singletons
    llm.py                      ← get_llm() factory with lru_cache
    graph.py                    ← compiles and wires the graph, nothing else
    tracing.py                  ← LangSmith config placeholder
    config.py                   ← settings
    app.py                      ← FastAPI app, startup, shutdown
    api/
        schemas.py              ← CoSolveRequest, CoSolveResponse, Source, SuggestedQuestions
        routes.py               ← /ask endpoint ONLY, envelope translation
    workflow/
        nodes/
            similarity_node.py
            similarity_reflection_node.py
            operational_node.py
            operational_reflection_node.py
            strategy_node.py
            strategy_reflection_node.py
            strategy_escalation_node.py
            operational_escalation_node.py
            kpi_node.py
            kpi_reflection_node.py
            intent_classification_node.py
            question_readiness_node.py
            context_node.py
            router_node.py
            start_node.py
            response_formatter_node.py
            end_node.py
        routing.py              ← ALL conditional edge functions
        escalation_controller.py ← DEPRECATED escalation logic (retained for reference)
        model_policy.py         ← DEPRECATED model selection (retained for reference)
    infra/
        models.py               ← CaseSummary, KnowledgeSummary, EvidenceSummary
        embeddings.py           ← embedding model singleton
        blob_storage.py         ← unchanged
        case_search_client.py   ← Azure case search client
        evidence_search_client.py ← Azure evidence search client
        knowledge_search_client.py ← Azure knowledge search client
    ingestion/                  ← unchanged entirely
    utils/
        text.py                 ← unchanged
```

---

## State

One state class. One file. All graph fields live here.

```python
# backend/state.py
class IncidentGraphState(TypedDict, total=False):
    # Request fields — set at entry from CoSolveRequest
    case_id: str | None
    question: str
    session_id: str | None

    # Context fields — set by context_node
    case_context: dict | None
    case_status: str | None
    current_d_state: str | None

    # Reasoning fields — set by nodes
    classification: dict | None
    route: str | None
    question_ready: bool
    clarifying_question: str | None

    # Draft and result fields — set by nodes
    operational_draft: dict | None
    operational_result: dict | None
    operational_reflection: dict | None
    operational_escalated: bool
    similarity_draft: dict | None
    similarity_result: dict | None
    similarity_reflection: dict | None
    similarity_escalated: bool
    strategy_draft: dict | None
    strategy_result: dict | None
    strategy_reflection: dict | None
    strategy_escalated: bool
    kpi_metrics: dict | None
    kpi_interpretation: dict | None

    # Output field — set by response_formatter_node
    final_response: dict | None

    # Internal tracking
    _last_node: str
```

---

## Nodes

Each node is a module-level function in its own file.
The function receives state, calls an LLM (optionally with tools), returns a dict slice.

```python
# Pattern every node follows
def node_name(state: IncidentGraphState) -> dict:
    llm = get_llm(deployment="gpt-4o", temperature=0.2)
    response = llm.invoke(PROMPT.format(**state))
    return {"field_name": parse(response)}
```

Reflection nodes follow the same pattern — they are NOT special.
They just receive a draft field and return a reflection field.

---

## Tools

All search indexes are exposed as @tool functions.
The LLM reads the docstring to decide when to use each tool.
Docstrings are part of the architecture — they are mandatory and precise.

```python
# Pattern every tool follows
@tool
def search_similar_cases(query: str) -> list[dict]:
    """Search historical incident cases by semantic similarity.
    Use when the question asks about past incidents, patterns, or precedents.
    Returns a list of matching cases with metadata."""
    return case_retriever.get_relevant_documents(query)
```

Tools live in `backend/tools.py`. Retrievers are module-level singletons.
Nodes import the tools they need — never the retriever directly.

---

## LLM Selection Per Node

Each node declares its own LLM. This is intentional and explicit.

| Node type | Deployment | Temperature | Reason |
|---|---|---|---|
| Classification, routing | gpt-4o-mini | 0.0 | Fast, deterministic |
| Operational, similarity, strategy, kpi | gpt-4o | 0.2 | Balanced reasoning |
| Reflection nodes | gpt-4o | 0.0 | Strict, critical |
| Escalation nodes | gpt-4o | 0.4 | Creative alternatives |
| Response formatter | gpt-4o | 0.3 | Readable output |

---

## Graph

`graph.py` does one thing: compile the graph.
No business logic. No LLM calls. No instantiation of anything except the graph builder.

```python
# graph.py
from langgraph.graph import StateGraph
from backend.state import IncidentGraphState
from backend.workflow.nodes.similarity_node import similarity_node
# ... all node imports

def build_graph():
    graph = StateGraph(IncidentGraphState)
    graph.add_node("similarity_node", similarity_node)
    # ... all nodes
    # ... all edges
    return graph.compile()

compiled_graph = build_graph()
```

---

## API Contract

`routes.py` is the only place where the envelope meets the graph.
It does three things only:

1. Validate incoming `CoSolveRequest`
2. Convert it to `IncidentGraphState`
3. Run the graph
4. Convert `IncidentGraphState` to `CoSolveResponse`

Nothing from `IncidentGraphState` leaks to the UI directly.
Nothing from `CoSolveRequest` enters the graph directly.

---

## Memory Model

At startup per worker:
- `compiled_graph` — one instance, shared
- `get_llm()` instances — one per (deployment, temperature) pair, cached
- Retriever instances — one per index, module-level singletons in `tools.py`

Per request:
- `IncidentGraphState` — one dict, lives for duration of graph invocation, then GC'd

---

## What Does NOT Change

- `backend/infra/blob_storage.py` — untouched
- `backend/infra/embeddings.py` — untouched
- `backend/ingestion/` — untouched entirely
- `backend/utils/text.py` — untouched
- `backend/config.py` — untouched
- Azure indexes — untouched
- UI — untouched
- Graph topology — edges, conditional edges, routing logic all stay identical
- Prompt content — the reasoning inside each prompt stays, only the container changes
