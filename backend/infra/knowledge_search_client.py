from __future__ import annotations

import logging
from typing import Optional

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizedQuery


class KnowledgeSearchClient:
    def __init__(self, endpoint: str, index_name: str, admin_key: str) -> None:
        self._logger = logging.getLogger("knowledge_search_client")
        self._search_client = SearchClient(
            endpoint=endpoint,
            index_name=index_name,
            credential=AzureKeyCredential(admin_key),
            connection_timeout=10,
            read_timeout=10,
        )

    def hybrid_search(
        self,
        search_text: str,
        embedding: list[float],
        top_k: int,
        cosolve_phase: Optional[str] = None,
    ) -> list[dict]:
        """Two-stage retrieval: score on small_chunks, fetch parent sections."""

        # STAGE 1 — Score on small_chunk entries only
        # Filter to small_chunk type so BM25 + vector scoring is precise
        small_chunk_filter = "chunk_type eq 'small_chunk'"

        vector_query = VectorizedQuery(
            vector=embedding,
            fields="embedding",
            k_nearest_neighbors=top_k * 3,
        )
        raw_results = self._search_client.search(
            search_text=search_text or "*",
            vector_queries=[vector_query],
            filter=small_chunk_filter,
            select=[
                "doc_id",
                "parent_section_id",
                "source",
                "section_title",
                "cosolve_phase",
            ],
            top=top_k * 3,
        )

        # Collect unique parent_section_ids, preserving rank order
        seen_sources: set[str] = set()
        parent_ids: list[tuple[str, float]] = []
        for r in raw_results:
            r_dict = dict(r)
            pid = r_dict.get("parent_section_id")
            source = r_dict.get("source")
            if not pid:
                continue
            # Deduplicate: one section per source document
            if source in seen_sources:
                continue
            seen_sources.add(source)
            score = r_dict.get("@search.score") or 0.0
            parent_ids.append((pid, score))
            if len(parent_ids) >= top_k:
                break

        if not parent_ids:
            return []

        # STAGE 2 — Fetch parent section documents by ID
        sections: list[dict] = []
        for pid, score in parent_ids:
            try:
                doc = self._search_client.get_document(key=pid)
                if doc:
                    d = dict(doc)
                    d["@search.score"] = score
                    sections.append(d)
            except Exception:
                continue

        return sections


__all__ = ["KnowledgeSearchClient"]
