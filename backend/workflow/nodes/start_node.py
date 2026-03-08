from __future__ import annotations

from backend.state import IncidentGraphState


def start_node(state: IncidentGraphState) -> dict:
    """Reset escalation flags at the start of every graph run."""
    return {
        "operational_escalated": False,
        "strategy_escalated": False,
        "_last_node": "start_node",
    }


# DEPRECATED: replaced by start_node() function above — remove in Phase 8
class StartNode:
    def run(self) -> dict[str, bool]:
        return {
            "operational_escalated": False,
            "strategy_escalated": False,
        }


__all__ = ["StartNode"]
