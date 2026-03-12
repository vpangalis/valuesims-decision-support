"""Knowledge search — module-level functions wrapping AzureSearch VectorStore.

Searches directly on 'section' chunks which already contain the full
content_text, source, section_title, cosolve_phase, and their own embedding.
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

logger = logging.getLogger("knowledge_search_client")


@lru_cache(maxsize=1)
def _get_settings() -> Settings:
    return Settings()


@lru_cache(maxsize=1)
def _get_knowledge_vectorstore() -> AzureSearch:
    s = _get_settings()
    return AzureSearch(
        azure_search_endpoint=s.AZURE_SEARCH_ENDPOINT,
        azure_search_key=s.AZURE_SEARCH_ADMIN_KEY,
        index_name=s.KNOWLEDGE_INDEX_NAME,
        embedding_function=get_embeddings().embed_query,
    )


def hybrid_search_knowledge(
    query: str,
    top_k: int = 10,
    cosolve_phase: Optional[str] = None,
) -> list[dict]:
    """Hybrid BM25 + vector search on section chunks.

    Searches directly on chunk_type='section' documents which contain the full
    content_text, source filename, section_title, page range, and cosolve_phase.
    """
    logger.info("[KNOWLEDGE] hybrid_search query=%r top_k=%d phase=%r", query, top_k, cosolve_phase)

    filters = ["chunk_type eq 'section'"]
    if cosolve_phase:
        safe_phase = cosolve_phase.replace("'", "''")
        filters.append(f"cosolve_phase eq '{safe_phase}'")
    filter_expression = " and ".join(filters)

    docs_with_scores = _get_knowledge_vectorstore().similarity_search_with_relevance_scores(
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

    logger.info("[KNOWLEDGE] hybrid_search returned %d hits", len(results))
    return results


@lru_cache(maxsize=1)
def _get_knowledge_search_client() -> SearchClient:
    """Raw SDK client for admin operations (listing, deleting chunks)."""
    s = _get_settings()
    return SearchClient(
        endpoint=s.AZURE_SEARCH_ENDPOINT,
        index_name=s.KNOWLEDGE_INDEX_NAME,
        credential=AzureKeyCredential(s.AZURE_SEARCH_ADMIN_KEY),
    )


__all__ = ["hybrid_search_knowledge"]
