from __future__ import annotations

from typing import Literal, Optional

from backend.config import Settings
from backend.tools.kpi_tool import KPITool
from backend.workflow.models import KPINodeOutput, KPIResult


class KPINode:
    def _resolve_scope(
        self,
        classification_scope: str,
        case_id: Optional[str],
    ) -> Literal["global", "country", "case"]:
        """Map the graph intent scope to a KPITool scope.

        GLOBAL → global
        COUNTRY → country
        LOCAL (with case_id) → case
        LOCAL (without case_id) → global (graceful fallback)
        """
        if classification_scope == "GLOBAL":
            return "global"
        if classification_scope == "COUNTRY":
            return "country"
        # LOCAL scope
        return "case" if case_id else "global"

    def _extract_country(self, question: str) -> Optional[str]:
        """Pull a country name from 'country: <name>' in the question string."""
        marker = "country:"
        idx = question.lower().find(marker)
        if idx < 0:
            return None
        trailing = question[idx + len(marker) :].strip()
        if not trailing:
            return None
        return trailing.split()[0].strip(",.;")

    def __init__(self, kpi_tool: KPITool, settings: Settings) -> None:
        self._kpi_tool = kpi_tool
        self._settings = settings

    def run(
        self,
        question: str,
        case_id: Optional[str],
        classification_scope: str,
        country: Optional[str],
    ) -> KPINodeOutput:
        """Compute KPI metrics for the scope implied by the intent classification.

        Args:
            question:             User's original question (used for country extraction).
            case_id:              Currently loaded case ID, if any.
            classification_scope: 'GLOBAL' | 'COUNTRY' | 'LOCAL' from the classifier.
            country:              Country resolved by the graph, if any.
        """
        scope = self._resolve_scope(classification_scope, case_id)

        # If scope is country but we haven't resolved one yet, try extracting
        # it from the question text.
        effective_country = country or (
            self._extract_country(question) if scope == "country" else None
        )

        kpi_result: KPIResult = self._kpi_tool.get_kpis(
            scope=scope,
            country=effective_country,
            case_id=case_id if scope == "case" else None,
        )
        return KPINodeOutput(kpi_metrics=kpi_result)


__all__ = ["KPINode"]
