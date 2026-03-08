from __future__ import annotations

from typing import Literal, Optional

from backend.state import IncidentGraphState
from backend.config import Settings
from backend.infra.case_search_client import CaseSearchClient
from backend.infra.evidence_search_client import EvidenceSearchClient
from backend.infra.knowledge_search_client import KnowledgeSearchClient
from backend.infra.embeddings import EmbeddingClient
from backend.infra.blob_storage import BlobStorageClient, CaseReadRepository
from backend.retrieval.hybrid_retriever import HybridRetriever
from backend.tools.kpi_tool import KPITool
from backend.workflow.models import KPINodeOutput, KPIResult

_settings = Settings()
_retriever = HybridRetriever(
    case_search_client=CaseSearchClient(
        endpoint=_settings.AZURE_SEARCH_ENDPOINT,
        index_name=_settings.CASE_INDEX_NAME,
        admin_key=_settings.AZURE_SEARCH_ADMIN_KEY,
    ),
    evidence_search_client=EvidenceSearchClient(
        endpoint=_settings.AZURE_SEARCH_ENDPOINT,
        index_name=_settings.EVIDENCE_INDEX_NAME,
        admin_key=_settings.AZURE_SEARCH_ADMIN_KEY,
    ),
    knowledge_search_client=KnowledgeSearchClient(
        endpoint=_settings.AZURE_SEARCH_ENDPOINT,
        index_name=_settings.KNOWLEDGE_INDEX_NAME,
        admin_key=_settings.AZURE_SEARCH_ADMIN_KEY,
    ),
    embedding_client=EmbeddingClient(),
    settings=_settings,
)
_blob_client = BlobStorageClient(
    _settings.AZURE_STORAGE_CONNECTION_STRING,
    _settings.AZURE_STORAGE_CONTAINER,
)
_case_repo = CaseReadRepository(
    _settings.AZURE_STORAGE_CONNECTION_STRING,
    _settings.AZURE_STORAGE_CONTAINER,
)
_kpi_tool = KPITool(
    hybrid_retriever=_retriever,
    settings=_settings,
    case_repo=_case_repo,
)


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

    kpi_result: KPIResult = _kpi_tool.get_kpis(
        scope=scope,
        country=country,
        case_id=case_id if scope == "case" else None,
    )
    return {
        "kpi_metrics": kpi_result.model_dump(mode="json"),
        "_last_node": "kpi_node",
    }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

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


# DEPRECATED: replaced by kpi_node() function above — remove in Phase 8
class KPINode:
    def _resolve_scope(
        self, classification_scope: str, case_id: Optional[str],
    ) -> Literal["global", "country", "case"]:
        if classification_scope == "GLOBAL":
            return "global"
        if classification_scope == "COUNTRY":
            return "country"
        return "case" if case_id else "global"

    def _extract_country(self, question: str) -> Optional[str]:
        marker = "country:"
        idx = question.lower().find(marker)
        if idx < 0:
            return None
        trailing = question[idx + len(marker):].strip()
        if not trailing:
            return None
        return trailing.split()[0].strip(",.;")

    def __init__(self, kpi_tool: KPITool, settings: Settings) -> None:
        self._kpi_tool = kpi_tool
        self._settings = settings

    def run(
        self, question: str, case_id: Optional[str],
        classification_scope: str, country: Optional[str],
    ) -> KPINodeOutput:
        scope = self._resolve_scope(classification_scope, case_id)
        effective_country = country or (
            self._extract_country(question) if scope == "country" else None
        )
        kpi_result: KPIResult = self._kpi_tool.get_kpis(
            scope=scope, country=effective_country,
            case_id=case_id if scope == "case" else None,
        )
        return KPINodeOutput(kpi_metrics=kpi_result)


__all__ = ["KPINode"]
