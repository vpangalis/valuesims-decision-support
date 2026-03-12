"""Evidence search — module-level functions wrapping AzureSearch VectorStore.

Searches evidence documents semantically, scoped to a specific case via OData filter.
"""
from __future__ import annotations

import logging
from functools import lru_cache

from langchain_community.vectorstores.azuresearch import AzureSearch

from backend.core.config import Settings
from backend.knowledge.embeddings import get_embeddings

logger = logging.getLogger("evidence_search_client")


@lru_cache(maxsize=1)
def _get_settings() -> Settings:
    return Settings()


@lru_cache(maxsize=1)
def _get_evidence_vectorstore() -> AzureSearch:
    s = _get_settings()
    return AzureSearch(
        azure_search_endpoint=s.AZURE_SEARCH_ENDPOINT,
        azure_search_key=s.AZURE_SEARCH_ADMIN_KEY,
        index_name=s.EVIDENCE_INDEX_NAME,
        embedding_function=get_embeddings().embed_query,
    )


def search_evidence(
    query: str,
    case_id: str,
    top_k: int = 20,
) -> list[dict]:
    """Semantic search over evidence documents scoped to a specific case.

    Returns the evidence most relevant to the query, not all evidence for the case.
    """
    logger.info("[EVIDENCE] search query=%r case_id=%r top_k=%d", query, case_id, top_k)
    safe_case_id = case_id.replace("'", "''")
    filter_expression = f"case_id eq '{safe_case_id}'"

    docs_with_scores = _get_evidence_vectorstore().similarity_search_with_relevance_scores(
        query,
        k=top_k,
        filters=filter_expression,
    )

    results = []
    for doc, score in docs_with_scores:
        item = dict(doc.metadata)
        item["content_text"] = item.get("content_text") or doc.page_content
        item["@search.score"] = score
        results.append(item)

    logger.info("[EVIDENCE] search returned %d hits", len(results))
    return results


__all__ = ["search_evidence"]
