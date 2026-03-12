"""Case search — module-level functions wrapping AzureSearch VectorStore + raw SDK.

Hybrid search uses LangChain AzureSearch VectorStore (embedding handled internally).
Filtered and text searches use a thin SearchClient (no vector, no ranking bias).
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Optional

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from langchain_community.vectorstores.azuresearch import AzureSearch

from backend.core.config import Settings
from backend.knowledge.embeddings import get_embeddings

logger = logging.getLogger("case_search_client")

_SELECT_FIELDS = [
    "case_id", "doc_id", "status", "opening_date", "closure_date",
    "problem_description", "organization_country", "organization_site",
    "organization_unit", "ai_summary", "team_members", "current_stage",
    "discipline_completed",
]

_TEXT_SEARCH_FIELDS = [
    "case_id", "problem_description", "what_happened", "why_problem",
    "organization_country", "organization_site", "organization_unit",
    "who", "where", "when", "how_identified", "impact",
    "immediate_actions_text", "permanent_actions_text",
    "fishbone_text", "five_whys_text", "ai_summary", "team_members",
]


@lru_cache(maxsize=1)
def _get_settings() -> Settings:
    return Settings()


@lru_cache(maxsize=1)
def _get_case_vectorstore() -> AzureSearch:
    s = _get_settings()
    return AzureSearch(
        azure_search_endpoint=s.AZURE_SEARCH_ENDPOINT,
        azure_search_key=s.AZURE_SEARCH_ADMIN_KEY,
        index_name=s.CASE_INDEX_NAME,
        embedding_function=get_embeddings().embed_query,
    )


@lru_cache(maxsize=1)
def _get_case_search_client() -> SearchClient:
    """Thin SDK client for exhaustive filtered searches (KPI, case-by-id)."""
    s = _get_settings()
    return SearchClient(
        endpoint=s.AZURE_SEARCH_ENDPOINT,
        index_name=s.CASE_INDEX_NAME,
        credential=AzureKeyCredential(s.AZURE_SEARCH_ADMIN_KEY),
    )


def hybrid_search_cases(
    query: str,
    filter_expression: Optional[str] = None,
    top_k: int = 5,
) -> list[dict]:
    """Hybrid BM25 + vector search via LangChain VectorStore."""
    logger.info("[CASE] hybrid_search query=%r filter=%r top_k=%d", query, filter_expression, top_k)
    docs_with_scores = _get_case_vectorstore().similarity_search_with_relevance_scores(
        query,
        k=top_k,
        filters=filter_expression,
    )
    results = []
    for doc, score in docs_with_scores:
        item = dict(doc.metadata)
        item["@search.score"] = score
        results.append(item)
    logger.info("[CASE] hybrid_search returned %d hits", len(results))
    return results


def filtered_search_cases(
    filter_expression: str,
    top_k: int = 100,
) -> list[dict]:
    """Pure OData filter — no vector, no ranking. Used by KPI aggregation."""
    logger.info("[CASE] filtered_search filter=%r top_k=%d", filter_expression, top_k)
    results_iter = _get_case_search_client().search(
        search_text="*",
        filter=filter_expression,
        top=top_k,
        select=_SELECT_FIELDS,
    )
    hits = [dict(r) for r in results_iter]
    logger.info(
        "[CASE] filtered_search returned %d hit(s): %s",
        len(hits),
        [h.get("case_id") or h.get("doc_id") for h in hits],
    )
    return hits


def text_search_cases(
    query: str,
    top_k: int = 10,
) -> list[dict]:
    """BM25-only text search used by the case search UI.

    Wildcard queries (ending with '*') use Lucene full syntax with
    search_fields=None so Azure fans out across all searchable fields.
    """
    is_wildcard = query.strip().endswith("*")
    logger.info(
        "[CASE] text_search query=%r wildcard=%s top_k=%d", query, is_wildcard, top_k
    )
    results = _get_case_search_client().search(
        search_text=query,
        search_fields=None if is_wildcard else _TEXT_SEARCH_FIELDS,
        query_type="full" if is_wildcard else "simple",
        search_mode="any",
        top=top_k,
        select=_SELECT_FIELDS,
    )
    return [dict(r) for r in results]


__all__ = ["hybrid_search_cases", "filtered_search_cases", "text_search_cases"]
