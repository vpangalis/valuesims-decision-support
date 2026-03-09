"""Shared intent coercion utilities.

These are module-level pure functions (not methods) because they are used by
multiple unrelated node classes (IntentClassificationNode and
IntentReflectionNode). Moving them here eliminates the circular import that
would arise if either node imported from the other.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from backend.workflow.models import IntentClassificationResult


class _RawClassification(BaseModel):
    """Lenient parse model — accepts any string for intent/scope so enum
    validation never raises before our coercion step."""

    intent: str = "SIMILARITY_SEARCH"
    scope: str = "GLOBAL"
    confidence: float = 0.5

    model_config = {"extra": "ignore"}


_VALID_INTENTS: frozenset[str] = frozenset(
    {"OPERATIONAL_CASE", "SIMILARITY_SEARCH", "STRATEGY_ANALYSIS", "KPI_ANALYSIS"}
)
_VALID_SCOPES: frozenset[str] = frozenset({"LOCAL", "COUNTRY", "GLOBAL"})

# Ordered keyword → canonical-value mapping (first match wins).
_INTENT_KEYWORDS: list[tuple[str, str]] = [
    ("KPI", "KPI_ANALYSIS"),
    ("METRIC", "KPI_ANALYSIS"),
    ("COUNT", "KPI_ANALYSIS"),
    ("PERFORM", "KPI_ANALYSIS"),
    ("OPERATIONAL", "OPERATIONAL_CASE"),
    ("SIMILAR", "SIMILARITY_SEARCH"),
    ("SEARCH", "SIMILARITY_SEARCH"),
    ("STRATEGY", "STRATEGY_ANALYSIS"),
    ("STRATEGIC", "STRATEGY_ANALYSIS"),
    ("PORTFOLIO", "STRATEGY_ANALYSIS"),
    ("ANALYSIS", "STRATEGY_ANALYSIS"),
]
_SCOPE_KEYWORDS: list[tuple[str, str]] = [
    ("LOCAL", "LOCAL"),
    ("SITE", "LOCAL"),
    ("COUNTRY", "COUNTRY"),
    ("GLOBAL", "GLOBAL"),
]


def coerce_intent(raw: str) -> str:
    """Map any LLM-returned intent string to a valid enum member."""
    normalised = re.sub(r"[^A-Z0-9]", "_", raw.strip().upper())
    if normalised in _VALID_INTENTS:
        return normalised
    for keyword, mapped in _INTENT_KEYWORDS:
        if keyword in normalised:
            return mapped
    return "SIMILARITY_SEARCH"


def coerce_scope(raw: str) -> str:
    """Map any LLM-returned scope string to a valid enum member."""
    normalised = re.sub(r"[^A-Z0-9]", "_", raw.strip().upper())
    if normalised in _VALID_SCOPES:
        return normalised
    for keyword, mapped in _SCOPE_KEYWORDS:
        if keyword in normalised:
            return mapped
    return "GLOBAL"


def coerce_raw(raw: _RawClassification) -> IntentClassificationResult:
    """Produce a fully-valid IntentClassificationResult from a lenient parse."""
    return IntentClassificationResult(
        intent=coerce_intent(raw.intent),  # type: ignore[arg-type]
        scope=coerce_scope(raw.scope),  # type: ignore[arg-type]
        confidence=max(0.0, min(1.0, float(raw.confidence))),
    )


__all__ = ["_RawClassification", "coerce_intent", "coerce_scope", "coerce_raw"]
