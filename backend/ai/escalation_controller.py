from __future__ import annotations

# DEPRECATED: Logic inlined into backend/workflow/routing.py. Do not use.


class EscalationController:
    def should_escalate_operational(self, state: dict) -> bool:
        reflection = state.get("operational_reflection")
        if reflection is None:
            return False
        if state.get("operational_escalated"):
            return False
        if isinstance(reflection, dict):
            return bool(reflection.get("needs_escalation"))
        return bool(getattr(reflection, "needs_escalation", False))

    def should_escalate_strategy(self, state: dict) -> bool:
        reflection = state.get("strategy_reflection")
        if reflection is None:
            return False
        if state.get("strategy_escalated"):
            return False
        if isinstance(reflection, dict):
            return bool(reflection.get("needs_escalation"))
        return bool(getattr(reflection, "needs_escalation", False))

    def should_escalate_similarity(self, state: dict) -> bool:
        reflection = state.get("similarity_reflection")
        if reflection is None:
            return False
        if state.get("similarity_escalated"):
            return False
        if isinstance(reflection, dict):
            return (
                reflection.get("case_specificity") == "MISSING"
                or reflection.get("relevance_honesty") == "FORCED"
                or reflection.get("pattern_quality") == "MISSING"
                or reflection.get("general_advice_flagged") == "MISSING"
                or reflection.get("explore_next_quality") in ("MISSING", "GENERIC")
            )
        return False


__all__ = ["EscalationController"]
