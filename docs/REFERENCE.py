"""
REFERENCE.py — CoSolve Canonical Code Patterns

This file is NOT executed. It is the reference every Claude Code session
must read before writing any CoSolve code. Every pattern here must be
followed exactly. No deviations without explicit approval.
"""

# =============================================================================
# 1. STATE — backend/state.py
# =============================================================================

from __future__ import annotations
from typing import TypedDict

class IncidentGraphState(TypedDict, total=False):
    """Single source of truth for all graph state.
    All fields are optional (total=False) — nodes only set what they produce.
    """
    # Envelope fields — set from CoSolveRequest at entry
    case_id: str | None
    question: str
    session_id: str | None

    # Context
    case_context: dict | None
    case_status: str | None
    current_d_state: str | None

    # Reasoning
    classification: dict | None
    route: str | None
    question_ready: bool
    clarifying_question: str | None

    # Node outputs — dicts, never Pydantic models
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
    final_response: dict | None

    # Internal
    _last_node: str


# =============================================================================
# 2. TOOLS — backend/tools.py
# =============================================================================

import os
from langchain_community.retrievers import AzureAISearchRetriever
from langchain_core.tools import tool

# --- Retriever singletons — instantiated once at module load ---

_case_retriever = AzureAISearchRetriever(
    service_name=os.environ["AZURE_SEARCH_SERVICE"],
    index_name=os.environ["AZURE_SEARCH_CASES_INDEX"],
    api_key=os.environ["AZURE_SEARCH_KEY"],
    content_key="content",
    top_k=5,
)

_evidence_retriever = AzureAISearchRetriever(
    service_name=os.environ["AZURE_SEARCH_SERVICE"],
    index_name=os.environ["AZURE_SEARCH_EVIDENCE_INDEX"],
    api_key=os.environ["AZURE_SEARCH_KEY"],
    content_key="content",
    top_k=5,
)

_knowledge_retriever = AzureAISearchRetriever(
    service_name=os.environ["AZURE_SEARCH_SERVICE"],
    index_name=os.environ["AZURE_SEARCH_KNOWLEDGE_INDEX"],
    api_key=os.environ["AZURE_SEARCH_KEY"],
    content_key="content",
    top_k=5,
)

# --- Tool functions — LLM reads docstring to decide when to use each ---

@tool
def search_similar_cases(query: str) -> list[dict]:
    """Search historical incident cases by semantic similarity.
    Use when the question asks about past incidents, patterns, or precedents.
    Returns a list of matching cases with title, case_id, and summary."""
    docs = _case_retriever.get_relevant_documents(query)
    return [{"content": d.page_content, **d.metadata} for d in docs]

@tool
def search_evidence(query: str) -> list[dict]:
    """Search evidence documents attached to incidents.
    Use when the question asks for technical evidence, reports, or findings.
    Returns a list of evidence documents with source and content."""
    docs = _evidence_retriever.get_relevant_documents(query)
    return [{"content": d.page_content, **d.metadata} for d in docs]

@tool
def search_knowledge_base(query: str) -> list[dict]:
    """Search the strategic knowledge base for best practices and guidance.
    Use when the question asks for strategy, recommendations, or general knowledge.
    Returns a list of knowledge articles with title and content."""
    docs = _knowledge_retriever.get_relevant_documents(query)
    return [{"content": d.page_content, **d.metadata} for d in docs]


# =============================================================================
# 3. NODE — backend/workflow/nodes/similarity_node.py
# =============================================================================

# One file. One function. No class. No __init__. No injection.

import json
from backend.state import IncidentGraphState
from backend.llm import get_llm
from backend.prompts import SIMILARITY_PROMPT
from backend.tools import search_similar_cases, search_evidence
from langgraph.prebuilt import create_react_agent

def similarity_node(state: IncidentGraphState) -> dict:
    """Find similar historical cases using semantic search."""
    llm = get_llm(deployment="gpt-4o", temperature=0.2)
    agent = create_react_agent(llm, tools=[search_similar_cases, search_evidence])
    response = agent.invoke({
        "messages": [("user", SIMILARITY_PROMPT.format(
            question=state.get("question", ""),
            case_context=json.dumps(state.get("case_context") or {}),
        ))]
    })
    # Return ONLY the fields this node produces — nothing else
    return {"similarity_draft": _parse_similarity(response)}

def _parse_similarity(response: dict) -> dict:
    """Extract structured output from agent response."""
    content = response["messages"][-1].content
    try:
        return json.loads(content)
    except Exception:
        return {"raw": content}


# =============================================================================
# 4. REFLECTION NODE — backend/workflow/nodes/similarity_reflection_node.py
# =============================================================================

# Reflection is just another function — not special, not a base class

from backend.state import IncidentGraphState
from backend.llm import get_llm
from backend.prompts import SIMILARITY_REFLECTION_PROMPT
import json

def similarity_reflection_node(state: IncidentGraphState) -> dict:
    """Critically assess the quality of the similarity search result."""
    llm = get_llm(deployment="gpt-4o", temperature=0.0)  # strict, critical
    response = llm.invoke(SIMILARITY_REFLECTION_PROMPT.format(
        question=state.get("question", ""),
        draft=json.dumps(state.get("similarity_draft") or {}),
    ))
    return {"similarity_reflection": _parse_reflection(response.content)}

def _parse_reflection(content: str) -> dict:
    try:
        return json.loads(content)
    except Exception:
        return {"raw": content}


# =============================================================================
# 5. ROUTING — backend/workflow/routing.py
# =============================================================================

# All conditional edge functions live here — plain functions, no class

from backend.state import IncidentGraphState

def route_intent(state: IncidentGraphState) -> str:
    route = state.get("route")
    if route not in {"OPERATIONAL_CASE", "SIMILARITY_SEARCH", "STRATEGY_ANALYSIS", "KPI_ANALYSIS"}:
        return "SIMILARITY_SEARCH"  # safe fallback
    return str(route)

def route_question_readiness(state: IncidentGraphState) -> str:
    return "NOT_READY" if not state.get("question_ready", True) else "READY"

def route_operational_escalation(state: IncidentGraphState) -> str:
    reflection = state.get("operational_reflection") or {}
    if isinstance(reflection, dict) and reflection.get("quality_score", 1.0) < 0.7:
        if not state.get("operational_escalated"):
            return "ESCALATE"
    return "CONTINUE"


# =============================================================================
# 6. GRAPH — backend/graph.py
# =============================================================================

# graph.py wires everything. No business logic here.

from langgraph.graph import StateGraph
from backend.state import IncidentGraphState
from backend.workflow.nodes.similarity_node import similarity_node
from backend.workflow.nodes.similarity_reflection_node import similarity_reflection_node
# ... all other node imports
from backend.workflow.routing import route_intent, route_question_readiness

def build_graph():
    graph = StateGraph(IncidentGraphState)

    graph.add_node("similarity_node", similarity_node)
    graph.add_node("similarity_reflection_node", similarity_reflection_node)
    # ... all nodes

    graph.add_edge("similarity_node", "similarity_reflection_node")
    # ... all edges

    return graph.compile()

compiled_graph = build_graph()


# =============================================================================
# 7. API CONTRACT — backend/api/schemas.py
# =============================================================================

from pydantic import BaseModel

class CoSolveRequest(BaseModel):
    """What the UI sends to the backend. Nothing else crosses the wire inbound."""
    question: str
    case_id: str | None = None
    session_id: str | None = None

class Source(BaseModel):
    case_id: str
    title: str
    relevance: float | None = None

class SuggestedQuestions(BaseModel):
    ask_your_team: list[str] = []
    ask_cosolve: list[str] = []

class CoSolveResponse(BaseModel):
    """What the backend returns to the UI. Nothing else crosses the wire outbound."""
    answer: str
    intent: str
    sources: list[Source] = []
    suggested_questions: SuggestedQuestions | None = None
    warning: str | None = None


# =============================================================================
# 8. ROUTE — backend/api/routes.py
# =============================================================================

# routes.py does ONE thing: translate envelope ↔ state

from fastapi import APIRouter
from backend.api.schemas import CoSolveRequest, CoSolveResponse
from backend.state import IncidentGraphState
from backend.graph import compiled_graph

router = APIRouter()

@router.post("/ask", response_model=CoSolveResponse)
async def ask(request: CoSolveRequest) -> CoSolveResponse:
    # 1 — envelope → state
    state: IncidentGraphState = {
        "question": request.question,
        "case_id": request.case_id,
        "session_id": request.session_id,
    }

    # 2 — run graph
    result = compiled_graph.invoke(state)

    # 3 — state → envelope
    return _build_response(result)

def _build_response(state: IncidentGraphState) -> CoSolveResponse:
    final = state.get("final_response") or {}
    return CoSolveResponse(
        answer=final.get("answer", ""),
        intent=str(state.get("route") or ""),
        sources=[Source(**s) for s in final.get("sources", [])],
        suggested_questions=SuggestedQuestions(**final.get("suggested_questions", {})),
        warning=final.get("warning"),
    )
