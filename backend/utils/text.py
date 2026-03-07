from __future__ import annotations


def normalize_action(action: str | None) -> str:
    """Canonical action text normalizer. Single source of truth."""
    value = (action or "").strip().upper()
    return value.replace("-", "_").replace(" ", "_")
