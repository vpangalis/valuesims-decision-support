from __future__ import annotations

import logging
from typing import Optional

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizedQuery

logger = logging.getLogger(__name__)


class CaseSearchClient:
    def __init__(self, endpoint: str, index_name: str, admin_key: str) -> None:
        self._logger = logging.getLogger("case_search_client")
        self._endpoint = endpoint
        self._index_name = index_name
        self._search_client = SearchClient(
            endpoint=endpoint,
            index_name=index_name,
            credential=AzureKeyCredential(admin_key),
        )

    def _default_select_fields(self) -> list[str]:
        return [
            "case_id",
            "doc_id",
            "status",
            "opening_date",
            "closure_date",
            "problem_description",
            "organization_country",
            "organization_site",
            "organization_unit",
            "ai_summary",
            "team_members",
        ]

    def hybrid_search(
        self,
        search_text: str,
        embedding: list[float],
        filter_expression: Optional[str],
        top_k: int,
    ) -> list[dict]:
        self._logger.info(
            "Running case hybrid search",
            extra={
                "search_text": search_text,
                "has_filter": bool(filter_expression),
                "top_k": top_k,
            },
        )
        vector_query = VectorizedQuery(
            vector=embedding,
            fields="content_vector",
            k_nearest_neighbors=top_k,
        )
        results = self._search_client.search(
            search_text=search_text or "*",
            vector_queries=[vector_query],
            filter=filter_expression,
            top=top_k,
            select=self._default_select_fields(),
        )
        return [dict(r) for r in results]

    def filtered_search(
        self,
        filter_expression: str,
        top_k: int,
    ) -> list[dict]:
        self._logger.info(
            "[SEARCH] filtered_search — filter=%r  top_k=%d", filter_expression, top_k
        )
        results_iter = self._search_client.search(
            search_text="*",
            filter=filter_expression,
            top=top_k,
            select=self._default_select_fields(),
        )
        hits = [dict(r) for r in results_iter]
        self._logger.info(
            "[SEARCH] filtered_search returned %d hit(s): %s",
            len(hits),
            [h.get("case_id") or h.get("doc_id") for h in hits],
        )
        return hits

    _TEXT_SEARCH_FIELDS: list[str] = [
        "problem_description",
        "what_happened",
        "why_problem",
        "organization_country",
        "organization_site",
        "organization_unit",
        "who",
        "where",
        "when",
        "how_identified",
        "impact",
        "immediate_actions_text",
        "permanent_actions_text",
        "fishbone_text",
        "five_whys_text",
        "ai_summary",
        "team_members",
    ]

    def text_search(
        self,
        search_text: str,
        top_k: int,
    ) -> list[dict]:
        """Full-text search across searchable fields (no vector)."""
        self._logger.info(
            "[SEARCH_ALL] query=%r  fields=%s",
            search_text,
            self._TEXT_SEARCH_FIELDS,
        )
        results = self._search_client.search(
            search_text=search_text,
            search_fields=self._TEXT_SEARCH_FIELDS,
            top=top_k,
            select=self._default_select_fields(),
        )
        return [dict(r) for r in results]


__all__ = ["CaseSearchClient"]
