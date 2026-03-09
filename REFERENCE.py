"""
REFERENCE.py — CoSolve Canonical Code Patterns
Version: 3.0 — 2026-03-09
Changes from v2.0:
  - get_llm() now takes role name ("intent" / "reasoning"), not Azure deployment name
  - state.py → state/__init__.py
  - tools.py → tools/__init__.py

NOT executed. Read before writing any CoSolve code.
Every pattern here must be followed exactly.
"""

# =============================================================================
# 1. CONFIG — backend/config.py (additions only)
# =============================================================================
# Add these two fields to the existing Settings class.
# These are the ONLY place Azure deployment names appear in the codebase.

class Settings:
    # ... existing fields unchanged ...

    # LLM role → Azure deployment mapping
    # Change these when Azure deployments change — node code never needs updating
    LLM_INTENT_DEPLOYMENT: str = "intent-model"        # gpt-4o-mini
    LLM_REASONING_DEPLOYMENT: str = "operational-premium"  # gpt-4o


# =============================================================================
# 2. LLM — backend/llm.py
# =============================================================================
# get_llm() resolves a logical role to an Azure deployment name.
# Nodes never see Azure deployment names.

from functools import lru_cache
from langchain_openai import AzureChatOpenAI
from backend.config import Settings

_settings = Settings()

_ROLE_MAP = {
    "intent":    _settings.LLM_INTENT_DEPLOYMENT,
    "reasoning": _settings.LLM_REASONING_DEPLOYMENT,
}

def get_llm(role: str, temperature: float) -> AzureChatOpenAI:
    """Resolve a logical role to an Azure deployment and return a cached LLM instance.

    Roles:
      "intent"    — fast, cheap model for classification and routing
      "reasoning" — powerful model for analysis, reflection, formatting

    Never pass an Azure deployment name directly. Always use a role.
    """
    deployment = _ROLE_MAP.get(role, role)  # fallback: treat as literal (backwards compat)
    return _get_cached_llm(deployment, temperature)

@lru_cache(maxsize=None)
def _get_cached_llm(deployment: str, temperature: float) -> AzureChatOpenAI:
    return AzureChatOpenAI(
        azure_deployment=deployment,
        temperature=temperature,
        # ... other Azure params from settings
    )


# =============================================================================
# 3. STATE — backend/state/__init__.py
# =============================================================================
from __future__ import annotations
from typing import TypedDict

class IncidentGraphState(TypedDict, total=False):
    """Single source of truth. All fields optional (total=False).
    Nodes return dict slices — only the keys they produce."""
    case_id: str | None
    question: str
    session_id: str | None
    case_context: dict | None
    case_status: str | None
    current_d_state: str | None
    classification: dict | None
    route: str | None
    question_ready: bool
    clarifying_question: str | None
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
    _last_node: str


# =============================================================================
# 4. NODE — backend/workflow/nodes/similarity_node.py
# =============================================================================
# One file. One function. No class. Role name only — no Azure name.

from backend.state import IncidentGraphState
from backend.llm import get_llm
from backend.prompts import SIMILARITY_SYSTEM_PROMPT
from backend.tools import search_similar_cases, search_knowledge_base
from langchain_core.messages import HumanMessage, SystemMessage
import json

def similarity_node(state: IncidentGraphState) -> dict:
    llm = get_llm("reasoning", 0.2)   # ← role name, never "gpt-4o" or "operational-premium"

    cases = search_similar_cases.invoke({
        "query": state.get("question", ""),
        "case_id": state.get("case_id"),
    })
    knowledge = search_knowledge_base.invoke({
        "query": state.get("question", ""),
        "cosolve_phase": "root_cause",
    })

    user_prompt = (
        f"USER QUESTION: {state.get('question', '')}\n"
        f"ACTIVE CASE STATUS: {(state.get('case_status') or 'open').lower()}\n\n"
        "--- ACTIVE CASE CONTEXT ---\n"
        f"{json.dumps(state.get('case_context') or {}, default=str)}\n\n"
        "--- RETRIEVED CLOSED CASES ---\n"
        f"{json.dumps(cases, default=str)}\n\n"
        "--- KNOWLEDGE BASE REFERENCES ---\n"
        f"{json.dumps(knowledge, default=str)}"
    )

    response = llm.invoke([
        SystemMessage(content=SIMILARITY_SYSTEM_PROMPT),
        HumanMessage(content=user_prompt),
    ])

    return {
        "similarity_draft": {
            "summary": response.content,
            "supporting_cases": cases,
        },
        "_last_node": "similarity_node",
    }


# =============================================================================
# 5. REFLECTION NODE — backend/workflow/nodes/similarity_reflection_node.py
# =============================================================================

from backend.state import IncidentGraphState
from backend.llm import get_llm
from backend.prompts import SIMILARITY_REFLECTION_PROMPT
from langchain_core.messages import HumanMessage, SystemMessage
import json

def similarity_reflection_node(state: IncidentGraphState) -> dict:
    llm = get_llm("reasoning", 0.0)   # ← strict, critical — role name only

    draft = state.get("similarity_draft") or {}
    response = llm.invoke([
        SystemMessage(content=SIMILARITY_REFLECTION_PROMPT),
        HumanMessage(content=json.dumps(draft, default=str)),
    ])

    try:
        reflection = json.loads(response.content)
    except Exception:
        reflection = {"raw": response.content}

    return {
        "similarity_reflection": reflection,
        "_last_node": "similarity_reflection_node",
    }


# =============================================================================
# 6. INTENT NODE — backend/workflow/nodes/intent_classification_node.py
# =============================================================================

from backend.state import IncidentGraphState
from backend.llm import get_llm
from backend.prompts import INTENT_CLASSIFICATION_PROMPT
from langchain_core.messages import HumanMessage, SystemMessage
import json

def intent_classification_node(state: IncidentGraphState) -> dict:
    llm = get_llm("intent", 0.0)   # ← fast model for classification

    response = llm.invoke([
        SystemMessage(content=INTENT_CLASSIFICATION_PROMPT),
        HumanMessage(content=state.get("question", "")),
    ])

    try:
        classification = json.loads(response.content)
    except Exception:
        classification = {"intent": "SIMILARITY_SEARCH", "raw": response.content}

    return {
        "classification": classification,
        "route": classification.get("intent"),
        "_last_node": "intent_classification_node",
    }


# =============================================================================
# 7. ESCALATION NODE — backend/workflow/nodes/operational_escalation_node.py
# =============================================================================

from backend.state import IncidentGraphState
from backend.llm import get_llm
from backend.prompts import OPERATIONAL_ESCALATION_PROMPT
from backend.tools import search_similar_cases, search_knowledge_base
from langchain_core.messages import HumanMessage, SystemMessage
import json

def operational_escalation_node(state: IncidentGraphState) -> dict:
    llm = get_llm("reasoning", 0.4)   # ← creative alternatives — role name only

    # ... escalation logic
    return {
        "operational_result": {},
        "operational_escalated": True,
        "_last_node": "operational_escalation_node",
    }


# =============================================================================
# 8. API SCHEMAS — backend/api/schemas.py
# =============================================================================
from pydantic import BaseModel

class CoSolveRequest(BaseModel):
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
    answer: str
    intent: str
    sources: list[Source] = []
    suggested_questions: SuggestedQuestions | None = None
    warning: str | None = None


# =============================================================================
# 9. ROUTE — backend/api/routes.py
# =============================================================================
from fastapi import APIRouter
from backend.api.schemas import CoSolveRequest, CoSolveResponse, Source, SuggestedQuestions
from backend.state import IncidentGraphState
from backend.graph import compiled_graph

router = APIRouter()

@router.post("/ask", response_model=CoSolveResponse)
async def ask(request: CoSolveRequest) -> CoSolveResponse:
    state: IncidentGraphState = {
        "question": request.question,
        "case_id": request.case_id,
        "session_id": request.session_id,
    }
    result = compiled_graph.invoke(state)
    return _build_response(result)

def _build_response(state: IncidentGraphState) -> CoSolveResponse:
    final = state.get("final_response") or {}
    return CoSolveResponse(
        answer=final.get("answer", ""),
        intent=str(state.get("route") or ""),
        sources=[Source(**s) for s in final.get("sources", [])],
        suggested_questions=SuggestedQuestions(**final.get("suggested_questions", {}))
            if final.get("suggested_questions") else None,
        warning=final.get("warning"),
    )
