from __future__ import annotations

from typing import Any

from backend.state import IncidentGraphState
from backend.config import Settings
from backend.ai.model_policy import ModelPolicy
from backend.workflow.nodes.strategy_node import _run_strategy
from backend.workflow.models import StrategyNodeOutput

_model_policy = ModelPolicy(Settings())


def strategy_escalation_node(state: IncidentGraphState) -> dict:
    """Re-run strategy reasoning with a premium model after reflection failure."""
    model_name = _model_policy.resolve_model("strategy", state)
    result = _run_strategy(state, model_name=model_name)
    result["_last_node"] = "strategy_escalation_node"
    return result


