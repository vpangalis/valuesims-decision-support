from __future__ import annotations

from backend.state import IncidentGraphState


def router_node(state: IncidentGraphState) -> dict:
    """Extract the classified intent and set the route key."""
    classification = state.get("classification") or {}
    route = classification.get("intent", "SIMILARITY_SEARCH") if isinstance(classification, dict) else "SIMILARITY_SEARCH"
    return {"route": route, "_last_node": "router_node"}


