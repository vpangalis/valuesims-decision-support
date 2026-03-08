"""All @tool functions wrapping retrieval logic.

HybridRetriever is dissolved — its methods live here as module-level
@tool functions. The search client instances are module-level singletons.
"""
from __future__ import annotations

import logging
from typing import Optional

from langchain_core.tools import tool

from backend.config import Settings
from backend.infra.case_search_client import CaseSearchClient
from backend.infra.evidence_search_client import EvidenceSearchClient
from backend.infra.knowledge_search_client import KnowledgeSearchClient
from backend.infra.embeddings import EmbeddingClient
from backend.retrieval.models import CaseSummary, EvidenceSummary, KnowledgeSummary

_logger = logging.getLogger("tools")

# ---------------------------------------------------------------------------
# Module-level singletons — instantiated once, shared across all nodes
# ---------------------------------------------------------------------------
_settings = Settings()

_case_client = CaseSearchClient(
    endpoint=_settings.AZURE_SEARCH_ENDPOINT,
    index_name=_settings.CASE_INDEX_NAME,
    admin_key=_settings.AZURE_SEARCH_ADMIN_KEY,
)
_evidence_client = EvidenceSearchClient(
    endpoint=_settings.AZURE_SEARCH_ENDPOINT,
    index_name=_settings.EVIDENCE_INDEX_NAME,
    admin_key=_settings.AZURE_SEARCH_ADMIN_KEY,
)
_knowledge_client = KnowledgeSearchClient(
    endpoint=_settings.AZURE_SEARCH_ENDPOINT,
    index_name=_settings.KNOWLEDGE_INDEX_NAME,
    admin_key=_settings.AZURE_SEARCH_ADMIN_KEY,
)
_embedding_client = EmbeddingClient()

# Minimum @search.score for a knowledge document to be returned.
# Results below this threshold are discarded before reaching any reasoning node.
# Azure hybrid search scores (BM25 + vector) typically range 0-4; 0.5 filters out
# low-confidence matches while allowing moderately relevant content through.
KNOWLEDGE_MIN_SCORE = 0.5


# ---------------------------------------------------------------------------
# Private helper — NOT a @tool
# ---------------------------------------------------------------------------

def _map_case_summary(item: dict) -> CaseSummary:
    """Map a raw search document to a CaseSummary, including the new
    KPI-relevant fields (current_stage, responsible_leader, department)."""
    team_members: list = item.get("team_members") or []
    responsible_leader: Optional[str] = team_members[0] if team_members else None
    return CaseSummary(
        case_id=str(item.get("case_id")),
        organization_country=item.get("organization_country"),
        organization_site=item.get("organization_site"),
        opening_date=item.get("opening_date"),
        closure_date=item.get("closure_date"),
        problem_description=item.get("problem_description"),
        five_whys_text=item.get("five_whys_text"),
        permanent_actions_text=item.get("permanent_actions_text"),
        ai_summary=item.get("ai_summary"),
        status=item.get("status"),
        current_stage=item.get("current_stage"),
        responsible_leader=responsible_leader,
        department=item.get("organization_unit"),
        discipline_completed=item.get("discipline_completed"),
    )


# ---------------------------------------------------------------------------
# @tool functions
# ---------------------------------------------------------------------------

@tool
def search_similar_cases(
    query: str,
    current_case_id: Optional[str] = None,
    country: Optional[str] = None,
    top_k: Optional[int] = None,
) -> list[CaseSummary]:
    """Search closed incident cases by hybrid BM25 + vector similarity.
    Use when the question asks about past incidents, precedents, or failure patterns.
    Excludes the currently active case. Filters by country when provided.
    Returns case_id, problem_description, five_whys_text, permanent_actions_text."""
    effective_top_k = (
        top_k if top_k is not None else _settings.RETRIEVAL_SIMILAR_CASES_TOP_K
    )
    embedding = _embedding_client.generate_embedding(query)

    filters = ["status eq 'closed'"]
    if current_case_id:
        safe_case_id = current_case_id.replace("'", "''")
        filters.append(f"case_id ne '{safe_case_id}'")
    if country:
        safe_country = country.replace("'", "''")
        filters.append(f"organization_country eq '{safe_country}'")
    filter_expression = " and ".join(filters)

    _logger.info(
        "Retrieving similar cases",
        extra={
            "query": query,
            "current_case_id": current_case_id,
            "country": country,
            "top_k": effective_top_k,
        },
    )
    raw_results = _case_client.hybrid_search(
        search_text=query,
        embedding=embedding,
        filter_expression=filter_expression,
        top_k=effective_top_k,
    )

    mapped: list[CaseSummary] = []
    for item in raw_results:
        case_id = item.get("case_id")
        if not case_id:
            continue
        mapped.append(
            CaseSummary(
                case_id=str(case_id),
                organization_country=item.get("organization_country"),
                organization_site=item.get("organization_site"),
                opening_date=item.get("opening_date"),
                closure_date=item.get("closure_date"),
                problem_description=item.get("problem_description"),
                five_whys_text=item.get("five_whys_text"),
                permanent_actions_text=item.get("permanent_actions_text"),
                ai_summary=item.get("ai_summary"),
            )
        )
    return mapped


@tool
def search_cases_for_pattern_analysis(
    query: str,
    country: Optional[str] = None,
    top_k: Optional[int] = None,
) -> list[CaseSummary]:
    """Search closed incident cases for portfolio-level pattern analysis.
    Use when the question asks about systemic trends, recurring failures,
    or organisational weaknesses across the case portfolio.
    Does not exclude any specific case. Filters by country when provided.
    Returns case_id, problem_description, five_whys_text, permanent_actions_text."""
    effective_top_k = (
        top_k if top_k is not None else _settings.RETRIEVAL_PATTERN_CASES_TOP_K
    )
    embedding = _embedding_client.generate_embedding(query)

    filters = ["status eq 'closed'"]
    if country:
        safe_country = country.replace("'", "''")
        filters.append(f"organization_country eq '{safe_country}'")
    filter_expression = " and ".join(filters)

    _logger.info(
        "Retrieving cases for pattern analysis",
        extra={
            "query": query,
            "country": country,
            "top_k": effective_top_k,
        },
    )
    raw_results = _case_client.hybrid_search(
        search_text=query,
        embedding=embedding,
        filter_expression=filter_expression,
        top_k=effective_top_k,
    )

    mapped: list[CaseSummary] = []
    for item in raw_results:
        case_id = item.get("case_id")
        if not case_id:
            continue
        mapped.append(
            CaseSummary(
                case_id=str(case_id),
                organization_country=item.get("organization_country"),
                organization_site=item.get("organization_site"),
                opening_date=item.get("opening_date"),
                closure_date=item.get("closure_date"),
                problem_description=item.get("problem_description"),
                five_whys_text=item.get("five_whys_text"),
                permanent_actions_text=item.get("permanent_actions_text"),
                ai_summary=item.get("ai_summary"),
            )
        )
    _logger.info(
        "[HYBRID_RETRIEVER_DEBUG] retrieve_cases_for_pattern_analysis '%s' → %d results",
        query,
        len(mapped),
    )
    return mapped


@tool
def search_cases_for_kpi(
    country: Optional[str] = None,
) -> list[CaseSummary]:
    """Retrieve closed cases for KPI and trend analysis.
    Use when the question asks about metrics, recurrence rates, average closure times,
    or fleet-wide performance indicators for closed cases.
    Returns status, current_stage, opening_date, closure_date, department."""
    effective_top_k = _settings.RETRIEVAL_KPI_CASES_TOP_K
    filters = ["status eq 'closed'"]
    if country:
        safe_country = country.replace("'", "''")
        filters.append(f"organization_country eq '{safe_country}'")
    filter_expression = " and ".join(filters)

    _logger.info(
        "Retrieving cases for KPI",
        extra={"country": country, "top_k": effective_top_k},
    )
    raw_results = _case_client.filtered_search(
        filter_expression=filter_expression,
        top_k=effective_top_k,
    )

    return [
        _map_case_summary(item) for item in raw_results if item.get("case_id")
    ]


@tool
def search_active_cases_for_kpi(
    country: Optional[str] = None,
    top_k: int = 200,
) -> list[CaseSummary]:
    """Retrieve active (non-closed) cases for D-stage distribution and overdue analysis.
    Use when the question asks about currently open cases, active investigation stages,
    or overdue metrics.
    Returns status, current_stage, opening_date, department."""
    filters = ["status ne 'closed'"]
    if country:
        safe_country = country.replace("'", "''")
        filters.append(f"organization_country eq '{safe_country}'")
    filter_expression = " and ".join(filters)

    _logger.info(
        "Retrieving active cases for KPI",
        extra={"country": country, "top_k": top_k},
    )
    raw_results = _case_client.filtered_search(
        filter_expression=filter_expression,
        top_k=top_k,
    )
    return [
        _map_case_summary(item) for item in raw_results if item.get("case_id")
    ]


@tool
def search_case_by_id(
    case_id: str,
) -> Optional[CaseSummary]:
    """Retrieve a single case by case_id for case-scope KPI analysis.
    Use when the question targets a specific known case ID.
    Returns a single CaseSummary or None if not found."""
    safe_id = case_id.replace("'", "''")
    raw_results = _case_client.filtered_search(
        filter_expression=f"case_id eq '{safe_id}'",
        top_k=1,
    )
    if not raw_results:
        return None
    return _map_case_summary(raw_results[0])


@tool
def search_knowledge_base(
    query: str,
    top_k: Optional[int] = None,
    cosolve_phase: Optional[str] = None,
) -> list[KnowledgeSummary]:
    """Search the strategic knowledge base for best practices and guidance.
    Use when the question asks for methodology, strategy, engineering knowledge,
    or standards/procedures references.
    Filter by cosolve_phase (root_cause, corrective_action, prevent, etc.) when relevant.
    Returns doc_id, title, source, content_text, section_title, score."""
    effective_top_k = (
        top_k if top_k is not None else _settings.RETRIEVAL_KNOWLEDGE_TOP_K
    )
    embedding = _embedding_client.generate_embedding(query)

    _logger.info(
        "Retrieving knowledge",
        extra={"query": query, "top_k": effective_top_k},
    )
    raw_results = _knowledge_client.hybrid_search(
        search_text=query,
        embedding=embedding,
        top_k=effective_top_k,
        cosolve_phase=cosolve_phase,
    )

    mapped: list[KnowledgeSummary] = []
    for item in raw_results:
        doc_id = item.get("doc_id")
        if not doc_id:
            continue
        mapped.append(
            KnowledgeSummary(
                doc_id=str(doc_id),
                title=item.get("title"),
                source=item.get("source"),
                content_text=item.get("content_text"),
                created_at=item.get("created_at"),
                chunk_type=item.get("chunk_type"),
                section_title=item.get("section_title"),
                parent_section_id=item.get("parent_section_id"),
                page_start=item.get("page_start"),
                page_end=item.get("page_end"),
                cosolve_phase=item.get("cosolve_phase"),
                char_count=item.get("char_count"),
                score=item.get("@search.score"),
            )
        )
    # Drop results below the absolute minimum relevance threshold.
    # Do NOT fall back to low-scoring results; return an empty list instead.
    mapped = [k for k in mapped if (k.score or 0.0) >= KNOWLEDGE_MIN_SCORE]
    return mapped


@tool
def search_evidence(
    case_id: str,
    top_k: Optional[int] = None,
) -> list[EvidenceSummary]:
    """Retrieve evidence documents attached to a specific incident case.
    Use when the question asks for technical reports, photos, lab results,
    or findings from a specific case.
    Returns case_id, filename, content_type, created_at."""
    effective_top_k = (
        top_k if top_k is not None else _settings.RETRIEVAL_EVIDENCE_TOP_K
    )
    _logger.info(
        "Retrieving evidence for case",
        extra={"case_id": case_id, "top_k": effective_top_k},
    )
    raw_results = _evidence_client.search_by_case_id(
        case_id=case_id,
        top_k=effective_top_k,
    )

    mapped: list[EvidenceSummary] = []
    for item in raw_results:
        result_case_id = item.get("case_id")
        filename = item.get("filename") or item.get("source")
        if not result_case_id or not filename:
            continue
        mapped.append(
            EvidenceSummary(
                case_id=str(result_case_id),
                filename=str(filename),
                content_type=item.get("content_type") or item.get("evidence_type"),
                created_at=item.get("created_at"),
            )
        )
    return mapped


__all__ = [
    "search_similar_cases",
    "search_cases_for_pattern_analysis",
    "search_cases_for_kpi",
    "search_active_cases_for_kpi",
    "search_case_by_id",
    "search_knowledge_base",
    "search_evidence",
    "KNOWLEDGE_MIN_SCORE",
]
