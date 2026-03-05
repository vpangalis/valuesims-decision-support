from __future__ import annotations

import logging
from typing import Optional

from backend.config import Settings

# Minimum @search.score for a knowledge document to be returned.
# Results below this threshold are discarded before reaching any reasoning node.
# Azure hybrid search scores (BM25 + vector) typically range 0–4; 0.5 filters out
# low-confidence matches while allowing moderately relevant content through.
KNOWLEDGE_MIN_SCORE = 0.5
from backend.infra.case_search_client import CaseSearchClient
from backend.infra.evidence_search_client import EvidenceSearchClient
from backend.infra.knowledge_search_client import KnowledgeSearchClient
from backend.infra.embeddings import EmbeddingClient
from backend.retrieval.models import CaseSummary, EvidenceSummary, KnowledgeSummary


class HybridRetriever:
    def __init__(
        self,
        case_search_client: CaseSearchClient,
        evidence_search_client: EvidenceSearchClient,
        knowledge_search_client: KnowledgeSearchClient,
        embedding_client: EmbeddingClient,
        settings: Settings,
    ) -> None:
        self._case_search_client = case_search_client
        self._evidence_search_client = evidence_search_client
        self._knowledge_search_client = knowledge_search_client
        self._embedding_client = embedding_client
        self._settings = settings
        self._logger = logging.getLogger("hybrid_retriever")

    def retrieve_similar_cases(
        self,
        query: str,
        current_case_id: Optional[str],
        country: Optional[str],
        top_k: Optional[int] = None,
    ) -> list[CaseSummary]:
        effective_top_k = (
            top_k if top_k is not None else self._settings.RETRIEVAL_SIMILAR_CASES_TOP_K
        )
        embedding = self._embedding_client.generate_embedding(query)

        filters = ["status eq 'closed'"]
        if current_case_id:
            safe_case_id = current_case_id.replace("'", "''")
            filters.append(f"case_id ne '{safe_case_id}'")
        if country:
            safe_country = country.replace("'", "''")
            filters.append(f"organization_country eq '{safe_country}'")
        filter_expression = " and ".join(filters)

        self._logger.info(
            "Retrieving similar cases",
            extra={
                "query": query,
                "current_case_id": current_case_id,
                "country": country,
                "top_k": effective_top_k,
            },
        )
        raw_results = self._case_search_client.hybrid_search(
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

    def retrieve_cases_for_pattern_analysis(
        self,
        query: str,
        country: Optional[str],
        top_k: Optional[int] = None,
    ) -> list[CaseSummary]:
        effective_top_k = (
            top_k if top_k is not None else self._settings.RETRIEVAL_PATTERN_CASES_TOP_K
        )
        embedding = self._embedding_client.generate_embedding(query)

        filters = ["status eq 'closed'"]
        if country:
            safe_country = country.replace("'", "''")
            filters.append(f"organization_country eq '{safe_country}'")
        filter_expression = " and ".join(filters)

        self._logger.info(
            "Retrieving cases for pattern analysis",
            extra={
                "query": query,
                "country": country,
                "top_k": effective_top_k,
            },
        )
        raw_results = self._case_search_client.hybrid_search(
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
        self._logger.info(
            "[HYBRID_RETRIEVER_DEBUG] retrieve_cases_for_pattern_analysis '%s' → %d results",
            query,
            len(mapped),
        )
        return mapped

    def retrieve_cases_for_kpi(
        self,
        country: Optional[str],
    ) -> list[CaseSummary]:
        effective_top_k = self._settings.RETRIEVAL_KPI_CASES_TOP_K
        filters = ["status eq 'closed'"]
        if country:
            safe_country = country.replace("'", "''")
            filters.append(f"organization_country eq '{safe_country}'")
        filter_expression = " and ".join(filters)

        self._logger.info(
            "Retrieving cases for KPI",
            extra={"country": country, "top_k": effective_top_k},
        )
        raw_results = self._case_search_client.filtered_search(
            filter_expression=filter_expression,
            top_k=effective_top_k,
        )

        return [
            self._map_case_summary(item) for item in raw_results if item.get("case_id")
        ]

    def retrieve_active_cases_for_kpi(
        self,
        country: Optional[str],
        top_k: int = 200,
    ) -> list[CaseSummary]:
        """Retrieve active (non-closed) cases for D-stage distribution and
        overdue analysis."""
        filters = ["status ne 'closed'"]
        if country:
            safe_country = country.replace("'", "''")
            filters.append(f"organization_country eq '{safe_country}'")
        filter_expression = " and ".join(filters)

        self._logger.info(
            "Retrieving active cases for KPI",
            extra={"country": country, "top_k": top_k},
        )
        raw_results = self._case_search_client.filtered_search(
            filter_expression=filter_expression,
            top_k=top_k,
        )
        return [
            self._map_case_summary(item) for item in raw_results if item.get("case_id")
        ]

    def retrieve_case_by_id(self, case_id: str) -> Optional[CaseSummary]:
        """Retrieve a single case by case_id for case-scope KPI analysis."""
        safe_id = case_id.replace("'", "''")
        raw_results = self._case_search_client.filtered_search(
            filter_expression=f"case_id eq '{safe_id}'",
            top_k=1,
        )
        if not raw_results:
            return None
        return self._map_case_summary(raw_results[0])

    def _map_case_summary(self, item: dict) -> CaseSummary:
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

    def retrieve_knowledge(
        self,
        query: str,
        top_k: Optional[int] = None,
        cosolve_phase: Optional[str] = None,
    ) -> list[KnowledgeSummary]:
        effective_top_k = (
            top_k if top_k is not None else self._settings.RETRIEVAL_KNOWLEDGE_TOP_K
        )
        embedding = self._embedding_client.generate_embedding(query)

        self._logger.info(
            "Retrieving knowledge",
            extra={"query": query, "top_k": effective_top_k},
        )
        raw_results = self._knowledge_search_client.hybrid_search(
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

    def retrieve_evidence_for_case(
        self,
        case_id: str,
        top_k: Optional[int] = None,
    ) -> list[EvidenceSummary]:
        effective_top_k = (
            top_k if top_k is not None else self._settings.RETRIEVAL_EVIDENCE_TOP_K
        )
        self._logger.info(
            "Retrieving evidence for case",
            extra={"case_id": case_id, "top_k": effective_top_k},
        )
        raw_results = self._evidence_search_client.search_by_case_id(
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


__all__ = ["HybridRetriever"]
