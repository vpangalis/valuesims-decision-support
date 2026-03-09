from __future__ import annotations

from typing import Any

from backend.state import IncidentGraphState
from backend.config import Settings
from backend.ai.model_policy import ModelPolicy
from backend.workflow.nodes.operational_node import _run_operational
from backend.workflow.models import OperationalNodeOutput

_model_policy = ModelPolicy(Settings())


def operational_escalation_node(state: IncidentGraphState) -> dict:
    """Re-run operational reasoning with a premium model after reflection failure."""
    model_name = _model_policy.resolve_model("operational", state)
    result = _run_operational(state, model_name=model_name)
    result["operational_escalated"] = True
    result["_last_node"] = "operational_escalation_node"
    return result


