from __future__ import annotations

from backend.state import IncidentGraphState
from backend.workflow.nodes.operational_node import _run_operational


def operational_escalation_node(state: IncidentGraphState) -> dict:
    """Re-run operational reasoning with premium model after reflection failure."""
    result = _run_operational(state, model_name="reasoning")
    result["operational_escalated"] = True
    result["_last_node"] = "operational_escalation_node"
    return result
