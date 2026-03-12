from __future__ import annotations

# DEPRECATED: Superseded by per-node get_llm() calls in llm.py. Do not use.

from backend.config import Settings


class ModelPolicy:
    def __init__(self, settings: Settings):
        self._intent_default = settings.MODEL_INTENT_CLASSIFIER
        self._operational_default = settings.MODEL_OPERATIONAL
        self._operational_premium = settings.MODEL_OPERATIONAL_PREMIUM
        self._strategy_default = settings.MODEL_STRATEGY
        self._strategy_premium = settings.MODEL_STRATEGY_PREMIUM

    def resolve_model(self, node_name: str, state: dict) -> str:
        if node_name == "operational":
            if state.get("operational_escalated") is True:
                return self._operational_premium
            return self._operational_default

        if node_name == "strategy":
            if state.get("strategy_escalated") is True:
                return self._strategy_premium
            return self._strategy_default

        return self._intent_default


__all__ = ["ModelPolicy"]
