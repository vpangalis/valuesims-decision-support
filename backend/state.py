from __future__ import annotations

from typing import TypedDict


class IncidentGraphState(TypedDict, total=False):
    """Single source of truth. All fields optional (total=False).
    Nodes return dict slices — only the keys they produce."""

    # Envelope fields — set from CoSolveRequest
    case_id: str | None
    question: str
    session_id: str | None

    # Context
    case_context: dict | None
    case_status: str | None
    current_d_state: str | None

    # Routing
    classification: dict | None
    route: str | None
    question_ready: bool
    clarifying_question: str | None

    # Node outputs — plain dicts only
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
    strategy_fail_section: str | None
    strategy_fail_reason: str | None
    strategy_response: str | None

    kpi_metrics: dict | None
    kpi_interpretation: dict | None

    final_response: dict | None
    _last_node: str
