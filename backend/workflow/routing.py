"""Conditional edge functions for the CoSolve LangGraph.

Extracted from UnifiedIncidentGraph._route_* methods.
No classes. No business logic beyond routing decisions.
"""
from __future__ import annotations

import logging

from backend.state import IncidentGraphState

_graph_logger = logging.getLogger("unified_incident_graph")


def route_question_readiness(state: IncidentGraphState) -> str:
    if not state.get("question_ready", True):
        _graph_logger.info(
            "[GRAPH_DEBUG] question not ready — short-circuiting to response_formatter"
        )
        return "NOT_READY"
    return "READY"


def route_intent(state: IncidentGraphState) -> str:
    route = state.get("route")
    _graph_logger.info("[GRAPH_DEBUG] routing decision: node_type=%s", route)
    if route not in {
        "OPERATIONAL_CASE",
        "SIMILARITY_SEARCH",
        "STRATEGY_ANALYSIS",
        "KPI_ANALYSIS",
    }:
        _graph_logger.warning(
            "[GRAPH_DEBUG] unexpected route value %r — falling back to SIMILARITY_SEARCH",
            route,
        )
        return "SIMILARITY_SEARCH"
    return str(route)


def route_operational_escalation(state: IncidentGraphState) -> str:
    # Closed case historical summaries skip the quality gate entirely.
    case_context = state.get("case_context")
    if extract_case_status(case_context) == "closed":
        return "CONTINUE"
    # Inline escalation logic (from EscalationController.should_escalate_operational)
    reflection = state.get("operational_reflection")
    if reflection is None:
        return "CONTINUE"
    if state.get("operational_escalated"):
        return "CONTINUE"
    if isinstance(reflection, dict) and reflection.get("needs_escalation"):
        return "ESCALATE"
    return "CONTINUE"


def route_strategy_escalation(state: IncidentGraphState) -> str:
    # Inline escalation logic (from EscalationController.should_escalate_strategy)
    reflection = state.get("strategy_reflection")
    if reflection is None:
        return "CONTINUE"
    if state.get("strategy_escalated"):
        return "CONTINUE"
    if isinstance(reflection, dict) and reflection.get("needs_escalation"):
        return "ESCALATE"
    return "CONTINUE"


def extract_case_status(case_context: dict | None) -> str | None:
    """Extract the case status string from a case_context document.

    Supports two document shapes:
    - Nested:  case_context["case"]["status"]   (seeded/stored documents)
    - Flat:    case_context["status"]            (legacy or test fixtures)
    """
    if not isinstance(case_context, dict):
        return None
    nested = case_context.get("case")
    if isinstance(nested, dict):
        status = nested.get("status")
        if isinstance(status, str) and status.strip():
            return status.strip().lower()
    flat = case_context.get("status")
    if isinstance(flat, str) and flat.strip():
        return flat.strip().lower()
    return None


def resolve_country(state: IncidentGraphState) -> str | None:
    """Extract country from classification/question."""
    classification = state.get("classification")
    if classification is None:
        return None
    if isinstance(classification, dict) and classification.get("scope") == "GLOBAL":
        return None
    question = str(state.get("question") or "")
    marker = "country:"
    marker_index = question.lower().find(marker)
    if marker_index < 0:
        return None
    trailing = question[marker_index + len(marker):].strip()
    if not trailing:
        return None
    return trailing.split()[0].strip(",.;")
