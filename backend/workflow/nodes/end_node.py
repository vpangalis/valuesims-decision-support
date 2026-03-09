from __future__ import annotations

from backend.state import IncidentGraphState


def end_node(state: IncidentGraphState) -> dict:
    """Terminal node — no-op pass-through."""
    return {"_last_node": "end_node"}


