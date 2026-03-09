from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.state import IncidentGraphState


def response_formatter_node(state: IncidentGraphState) -> dict:
    """Format the final response payload from the appropriate reasoning result."""
    classification = state.get("classification")
    result_payload: dict[str, Any] = {}

    if isinstance(classification, dict):
        intent = classification.get("intent")
        if intent == "OPERATIONAL_CASE":
            result_payload = state.get("operational_result") or {}
        elif intent == "SIMILARITY_SEARCH":
            result_payload = state.get("similarity_result") or {}
        elif intent == "STRATEGY_ANALYSIS":
            result_payload = state.get("strategy_result") or {}
        elif intent == "KPI_ANALYSIS":
            result_payload = state.get("kpi_interpretation") or {}

    return {
        "final_response": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "classification": classification,
            "result": result_payload,
        },
        "_last_node": "response_formatter_node",
    }


