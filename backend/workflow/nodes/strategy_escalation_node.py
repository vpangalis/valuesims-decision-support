from __future__ import annotations

from backend.state import IncidentGraphState
from backend.workflow.nodes.strategy_node import _run_strategy


def strategy_escalation_node(state: IncidentGraphState) -> dict:
    """Re-run strategy reasoning with premium model after reflection failure."""
    result = _run_strategy(state, model_name="reasoning")
    result["_last_node"] = "strategy_escalation_node"
    return result
