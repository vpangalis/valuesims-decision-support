from __future__ import annotations

from functools import lru_cache
from typing import Literal, Optional

from backend.state import IncidentGraphState
from backend.config import Settings
from backend.infra.case_search_client import CaseSearchClient
from backend.infra.blob_storage import CaseReadRepository
from backend.tools.kpi_tool import KPITool
from backend.workflow.models import KPIResult


@lru_cache(maxsize=1)
def _get_kpi_tool() -> KPITool:
    s = Settings()
    repo = CaseReadRepository(
        s.AZURE_STORAGE_CONNECTION_STRING,
        s.AZURE_STORAGE_CONTAINER,
    )
    client = CaseSearchClient(
        endpoint=s.AZURE_SEARCH_ENDPOINT,
        index_name=s.CASE_INDEX_NAME,
        admin_key=s.AZURE_SEARCH_ADMIN_KEY,
    )
    return KPITool(case_search_client=client, settings=s, case_repo=repo)


def kpi_node(state: IncidentGraphState) -> dict:
    """Compute KPI metrics for the scope implied by the intent classification."""
    question = state.get("question", "")
    case_id = state.get("case_id")
    classification = state.get("classification") or {}
    classification_scope = (
        classification.get("scope", "GLOBAL")
        if isinstance(classification, dict)
        else "GLOBAL"
    )
    country = _resolve_country(state, question, classification_scope)

    scope = _resolve_scope(classification_scope, case_id)

    kpi_result: KPIResult = _get_kpi_tool().get_kpis(
        scope=scope,
        country=country,
        case_id=case_id if scope == "case" else None,
    )
    return {
        "kpi_metrics": _kpi_result_to_dict(kpi_result),
        "_last_node": "kpi_node",
    }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _kpi_result_to_dict(result) -> dict:
    """Convert KPIResult to plain dict for state storage."""
    return result.model_dump(mode="json")


def _resolve_scope(
    classification_scope: str,
    case_id: str | None,
) -> Literal["global", "country", "case"]:
    if classification_scope == "GLOBAL":
        return "global"
    if classification_scope == "COUNTRY":
        return "country"
    return "case" if case_id else "global"


def _resolve_country(
    state: IncidentGraphState,
    question: str,
    classification_scope: str,
) -> str | None:
    """Try case context first, then fall back to parsing the question."""
    case_context = state.get("case_context") or {}
    if isinstance(case_context, dict):
        direct = case_context.get("organization_country")
        if isinstance(direct, str) and direct.strip():
            return direct.strip()
    if classification_scope == "COUNTRY":
        return _extract_country_from_question(question)
    return None


def _extract_country_from_question(question: str) -> Optional[str]:
    marker = "country:"
    idx = question.lower().find(marker)
    if idx < 0:
        return None
    trailing = question[idx + len(marker):].strip()
    if not trailing:
        return None
    return trailing.split()[0].strip(",.;")
