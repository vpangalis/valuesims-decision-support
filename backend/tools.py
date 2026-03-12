"""All @tool functions wrapping retrieval logic, plus KPITool.

HybridRetriever is dissolved — its methods live here as module-level
@tool functions. The search client instances are module-level singletons.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, List, Literal, Optional

from langchain_core.tools import tool

from backend.config import Settings
from backend.infra.blob_storage import CaseReadRepository
from backend.infra.case_search_client import CaseSearchClient
from backend.infra.evidence_search_client import EvidenceSearchClient
from backend.infra.knowledge_search_client import KnowledgeSearchClient
from backend.infra.embeddings import EmbeddingClient
from backend.infra.models import CaseSummary, EvidenceSummary, KnowledgeSummary
from backend.workflow.models import KPIResult

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


# ---------------------------------------------------------------------------
# KPITool — KPI analytics class
# ---------------------------------------------------------------------------

logger = logging.getLogger("kpi_tool")


class KPITool:
    """Computes KPI metrics for global, country, and case scopes."""

    # Default resolution SLA in calendar days.
    _DEFAULT_SLA_DAYS: int = 90

    # D-stage plain-language labels — never expose raw codes to users.
    _D_STAGE_LABELS: dict[str, str] = {
        "D1_D2": "Problem Definition",
        "D1_2": "Problem Definition",
        "D3": "Containment Actions",
        "D4": "Root Cause Analysis",
        "D5": "Permanent Corrective Actions",
        "D6": "Implementation & Validation",
        "D7": "Prevention",
        "D8": "Closure & Learnings",
    }

    def _utc_now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _to_utc(self, value: datetime | str | None) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc)
        if isinstance(value, str):
            s = value.strip()
            if not s:
                return None
            if s.endswith("Z"):
                s = s.replace("Z", "+00:00")
            try:
                dt = datetime.fromisoformat(s)
            except ValueError:
                return None
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        return None

    def _translate_stage(self, raw: str | None) -> str | None:
        """Return plain-language stage name, or the raw value if not mapped."""
        if raw is None:
            return None
        return KPITool._D_STAGE_LABELS.get(raw, raw)

    def __init__(
        self,
        case_search_client: CaseSearchClient,
        settings: Settings,
        case_repo: Optional[CaseReadRepository] = None,
    ) -> None:
        self._case_client = case_search_client
        self._settings = settings
        self._case_repo = case_repo

    # ──────────────────────────────────────────────────────────────────────
    # Inline retrieval helpers (moved from HybridRetriever)
    # ──────────────────────────────────────────────────────────────────────

    def _retrieve_cases_for_kpi(self, country: Optional[str]) -> list[CaseSummary]:
        effective_top_k = self._settings.RETRIEVAL_KPI_CASES_TOP_K
        filters = ["status eq 'closed'"]
        if country:
            safe_country = country.replace("'", "''")
            filters.append(f"organization_country eq '{safe_country}'")
        filter_expression = " and ".join(filters)
        raw_results = self._case_client.filtered_search(
            filter_expression=filter_expression,
            top_k=effective_top_k,
        )
        return [self._map_case_summary(item) for item in raw_results if item.get("case_id")]

    def _retrieve_active_cases_for_kpi(self, country: Optional[str], top_k: int = 200) -> list[CaseSummary]:
        filters = ["status ne 'closed'"]
        if country:
            safe_country = country.replace("'", "''")
            filters.append(f"organization_country eq '{safe_country}'")
        filter_expression = " and ".join(filters)
        raw_results = self._case_client.filtered_search(
            filter_expression=filter_expression,
            top_k=top_k,
        )
        return [self._map_case_summary(item) for item in raw_results if item.get("case_id")]

    def _retrieve_case_by_id(self, case_id: str) -> Optional[CaseSummary]:
        safe_id = case_id.replace("'", "''")
        raw_results = self._case_client.filtered_search(
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

    # ──────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────

    def get_kpis(
        self,
        scope: Literal["global", "country", "case"],
        country: Optional[str] = None,
        case_id: Optional[str] = None,
        year: Optional[int] = None,
        metrics: Optional[List[str]] = None,
    ) -> KPIResult:
        """Compute KPI metrics for the requested scope.

        Args:
            scope:    'global' | 'country' | 'case'
            country:  Country name (required when scope='country')
            case_id:  Case ID string (required when scope='case')
            year:     Filter to a specific calendar year (default: current year)
            metrics:  Optional list of specific metric names to compute
        """
        effective_year = year or self._utc_now().year
        if scope == "case":
            return self._case_scope(case_id=case_id, year=effective_year)
        if scope == "country":
            return self._country_scope(country=country, year=effective_year)
        return self._global_scope(year=effective_year)

    def calculate_metrics(self, country: str | None = None) -> KPIResult:
        """Backward-compat entry-point.  Delegates to get_kpis()."""
        scope: Literal["global", "country", "case"] = "country" if country else "global"
        return self.get_kpis(scope=scope, country=country)

    # ──────────────────────────────────────────────────────────────────────
    # Scope implementations
    # ──────────────────────────────────────────────────────────────────────

    def _global_scope(self, year: int) -> KPIResult:
        closed = self._retrieve_cases_for_kpi(country=None)
        active = self._retrieve_active_cases_for_kpi(country=None)
        now = self._utc_now()
        ytd_start = datetime(year, 1, 1, tzinfo=timezone.utc)
        rolling_start = now - timedelta(days=365)

        closed_ytd = [c for c in closed if self._opened_after(c, ytd_start)]
        closed_rolling = [c for c in closed if self._opened_after(c, rolling_start)]

        avg_ytd = self._avg_duration(closed_ytd)
        avg_rolling = self._avg_duration(closed_rolling)
        overdue = self._count_overdue(active, sla_days=KPITool._DEFAULT_SLA_DAYS)
        d_stage_dist = self._d_stage_distribution(active)
        country_ranking = self._build_country_ranking(closed)
        status_counts = self._compute_status_counts(active, len(closed))
        stage_avgs = self._compute_stage_avg_durations(country=None)

        suggestions = [
            f"Which country has the longest average resolution time in {year}?",
            "How many cases are currently overdue and in which countries?",
            "Show me the stage breakdown of all active cases right now.",
        ]

        return KPIResult(
            scope="global",
            scope_label="Global",
            render_hint="bar_chart" if country_ranking else "table",
            suggestions=suggestions,
            total_cases_opened_ytd=len(closed_ytd)
            + len([a for a in active if self._opened_after(a, ytd_start)]),
            total_cases_closed_ytd=len(closed_ytd),
            avg_closure_days_ytd=avg_ytd,
            avg_closure_days_rolling_12m=avg_rolling,
            first_closure_rate=self._first_closure_rate(closed),
            overdue_count=overdue,
            overdue_pct=self._pct(overdue, len(active)) if active else None,
            d_stage_distribution=d_stage_dist,
            country_ranking=country_ranking,
            total_closed_cases=len(closed),
            avg_closure_days=avg_ytd,
            min_closure_days=self._min_duration(closed_ytd),
            max_closure_days=self._max_duration(closed_ytd),
            open_count=status_counts["open"],
            in_progress_count=status_counts["in_progress"],
            avg_days_per_stage=stage_avgs or None,
            monthly_opened_closed=self._build_monthly_opened_closed(closed, active),
        )

    def _country_scope(self, country: str | None, year: int) -> KPIResult:
        if not country:
            return self._global_scope(year=year)

        closed = self._retrieve_cases_for_kpi(country=country)
        active = self._retrieve_active_cases_for_kpi(country=country)
        global_closed = self._retrieve_cases_for_kpi(country=None)
        ytd_start = datetime(year, 1, 1, tzinfo=timezone.utc)

        closed_ytd = [c for c in closed if self._opened_after(c, ytd_start)]
        avg_ytd = self._avg_duration(closed_ytd)
        overdue = self._count_overdue(active, sla_days=KPITool._DEFAULT_SLA_DAYS)
        status_counts = self._compute_status_counts(active, len(closed))
        stage_avgs = self._compute_stage_avg_durations(country=country)

        suggestions = [
            f"Which cases in {country} are currently overdue?",
            f"How does {country}'s average resolution time compare to the global average?",
            f"Show me the full breakdown of active cases in {country} right now.",
        ]

        return KPIResult(
            scope="country",
            scope_label=f"Country: {country}",
            render_hint="bar_chart",
            suggestions=suggestions,
            total_cases_opened_ytd=len(closed_ytd)
            + len([a for a in active if self._opened_after(a, ytd_start)]),
            total_cases_closed_ytd=len(closed_ytd),
            avg_closure_days_ytd=avg_ytd,
            avg_closure_days_rolling_12m=self._avg_duration(closed),
            first_closure_rate=self._first_closure_rate(closed),
            overdue_count=overdue,
            overdue_pct=self._pct(overdue, len(active)) if active else None,
            d_stage_distribution=self._d_stage_distribution(active),
            active_case_load=self._build_active_case_load(active),
            country_ranking=self._build_country_ranking(global_closed),
            ytd_closed_count=len(closed_ytd),
            global_avg_closure_days=self._avg_duration(global_closed),
            total_closed_cases=len(closed),
            avg_closure_days=avg_ytd,
            min_closure_days=self._min_duration(closed_ytd),
            max_closure_days=self._max_duration(closed_ytd),
            open_count=status_counts["open"],
            in_progress_count=status_counts["in_progress"],
            avg_days_per_stage=stage_avgs or None,
            monthly_opened_closed=self._build_monthly_opened_closed(closed, active),
        )

    def _case_scope(self, case_id: str | None, year: int) -> KPIResult:
        if not case_id:
            return self._global_scope(year=year)

        case = self._retrieve_case_by_id(case_id)
        if case is None:
            return KPIResult(
                scope="case",
                scope_label=f"Case: {case_id}",
                render_hint="summary_text",
                suggestions=[
                    "Open this case in the Case Board to see its full timeline.",
                    "Search for similar closed cases to find resolution benchmarks.",
                    "Check the global average resolution time for context.",
                ],
            )

        now = self._utc_now()
        opening = self._to_utc(case.opening_date)  # type: ignore[arg-type]
        is_closed = (case.status or "").lower() == "closed"
        closure = self._to_utc(case.closure_date) if is_closed else None  # type: ignore[arg-type]

        if is_closed and opening and closure:
            days_elapsed = (closure - opening).days
        else:
            days_elapsed = (now - opening).days if opening else None

        similar = self._retrieve_cases_for_kpi(country=None)
        benchmark = self._avg_duration(similar)
        plain_stage = self._translate_stage(case.current_stage)

        render_hint: Literal["table", "bar_chart", "gauge", "summary_text"] = (
            "gauge" if days_elapsed is not None else "summary_text"
        )

        if is_closed and days_elapsed is not None and benchmark is not None:
            benchmark_int = int(round(benchmark))
            gauge_label: str | None = (
                f"Closed in {days_elapsed} days vs {benchmark_int} day benchmark"
            )
            suggestions = [
                f"What were the root causes identified in case {case_id}?",
                f"Were the corrective actions in {case_id} effective long-term?",
                "Have similar cases been resolved faster than this one?",
            ]
        else:
            gauge_label = None
            suggestions = [
                f"How does case {case_id} compare to similar closed cases in resolution time?",
                f"What happened in the {plain_stage or 'current'} phase of this case?",
                "Show me the global average resolution time as a benchmark.",
            ]

        stage_timeline = self._compute_stage_timeline(case_id)

        return KPIResult(
            scope="case",
            scope_label=f"Case: {case_id}",
            render_hint=render_hint,
            suggestions=suggestions,
            days_elapsed=days_elapsed,
            gauge_label=gauge_label,
            category_benchmark_days=benchmark,
            current_stage=plain_stage,
            responsible_leader=case.responsible_leader,
            department=case.department,
            days_stuck_at_current_stage=days_elapsed,
            similar_cases_avg_resolution_days=benchmark,
            total_closed_cases=len(similar),
            avg_closure_days=benchmark,
            stage_timeline=stage_timeline or None,
        )

    # ──────────────────────────────────────────────────────────────────────
    # Pure helper static methods (no external I/O)
    # ──────────────────────────────────────────────────────────────────────

    def _opened_after(self, case: CaseSummary, cutoff: datetime) -> bool:
        opening = self._to_utc(case.opening_date)  # type: ignore[arg-type]
        return opening is not None and opening >= cutoff

    def _closure_duration(self, case: CaseSummary) -> int | None:
        opening = self._to_utc(case.opening_date)  # type: ignore[arg-type]
        closure = self._to_utc(case.closure_date)  # type: ignore[arg-type]
        if opening is None or closure is None:
            return None
        delta = (closure - opening).days
        return delta if delta >= 0 else None

    def _avg_duration(self, cases: list[CaseSummary]) -> float | None:
        durations = [
            d for d in (self._closure_duration(c) for c in cases) if d is not None
        ]
        if not durations:
            return None
        return round(sum(durations) / len(durations), 1)

    def _min_duration(self, cases: list[CaseSummary]) -> int | None:
        durations = [
            d for d in (self._closure_duration(c) for c in cases) if d is not None
        ]
        return min(durations) if durations else None

    def _max_duration(self, cases: list[CaseSummary]) -> int | None:
        durations = [
            d for d in (self._closure_duration(c) for c in cases) if d is not None
        ]
        return max(durations) if durations else None

    def _count_overdue(self, active_cases: list[CaseSummary], sla_days: int) -> int:
        cutoff = self._utc_now() - timedelta(days=sla_days)
        return sum(
            1
            for c in active_cases
            if (self._to_utc(c.opening_date) or datetime.max.replace(tzinfo=timezone.utc))  # type: ignore[arg-type]
            < cutoff
        )

    def _pct(self, part: int, total: int) -> float:
        return round(part / total * 100, 1) if total else 0.0

    def _d_stage_distribution(
        self,
        active_cases: list[CaseSummary],
    ) -> dict[str, int] | None:
        """Build a plain-language D-stage → count distribution from active cases."""
        counts: dict[str, int] = {}
        for c in active_cases:
            stage = self._translate_stage(c.current_stage) or "Unknown"
            counts[stage] = counts.get(stage, 0) + 1
        return counts if counts else None

    def _first_closure_rate(self, closed_cases: list[CaseSummary]) -> float | None:
        """Placeholder: returns 1.0 until the index tracks reopen events."""
        return 1.0 if closed_cases else None

    def _build_country_ranking(
        self,
        closed_cases: list[CaseSummary],
    ) -> list[dict[str, Any]]:
        """Group closed cases by country and rank by average resolution time."""
        by_country: dict[str, list[CaseSummary]] = {}
        for c in closed_cases:
            country = c.organization_country or "Unknown"
            by_country.setdefault(country, []).append(c)

        ranking: list[dict[str, Any]] = []
        for country, cases in by_country.items():
            avg = self._avg_duration(cases)
            if avg is None:
                continue
            ranking.append(
                {
                    "country": country,
                    "avg_closure_days": avg,
                    "total_closed": len(cases),
                }
            )

        ranking.sort(key=lambda r: r["avg_closure_days"])
        return ranking

    # ── Blob-side computation helpers ──────────────────────────────────────

    _PHASE_ORDER: list[str] = ["D1_2", "D3", "D4", "D5", "D6", "D7", "D8"]

    def _compute_stage_avg_durations(
        self, country: Optional[str] = None
    ) -> dict[str, float]:
        """Return avg days per stage using confirmed_at timestamps from blob."""
        if self._case_repo is None:
            return {}
        stage_durations: dict[str, list[int]] = {}
        try:
            paths = self._case_repo.list_case_paths()
        except Exception:
            logger.exception("[KPI] _compute_stage_avg_durations: list_case_paths failed")
            return {}
        for path in paths:
            try:
                case = self._case_repo.load_case(path)
                if country and (case.get("organization_country") or "").lower() != country.lower():
                    continue
                d_states = case.get("d_states") or {}
                prev_dt: Optional[datetime] = None
                for phase in self._PHASE_ORDER:
                    st = d_states.get(phase) or {}
                    if st.get("status") != "completed":
                        prev_dt = None
                        continue
                    raw = st.get("confirmed_at")
                    if not raw:
                        prev_dt = None
                        continue
                    try:
                        cur_dt = datetime.strptime(raw, "%Y-%m-%d")
                    except ValueError:
                        prev_dt = None
                        continue
                    if prev_dt is not None:
                        days = (cur_dt - prev_dt).days
                        if days >= 0:
                            stage_durations.setdefault(phase, []).append(days)
                    prev_dt = cur_dt
            except Exception:
                continue
        return {
            phase: round(sum(vals) / len(vals), 1)
            for phase, vals in stage_durations.items()
            if vals
        }

    def _compute_status_counts(
        self,
        active_cases: list,
        closed_count: int,
    ) -> dict[str, int]:
        """Classify active cases as open/in-progress using discipline_completed."""
        in_progress = sum(
            1 for c in active_cases
            if getattr(c, "discipline_completed", None)
        )
        open_count = len(active_cases) - in_progress
        return {"open": open_count, "in_progress": in_progress, "closed": closed_count}

    def _compute_stage_timeline(self, case_id: str) -> list[dict]:
        """Return per-stage timeline list from blob for one case."""
        if self._case_repo is None:
            return []
        try:
            case = self._case_repo.load_case(f"{case_id}/case.json")
            d_states = case.get("d_states") or {}
            opened_raw = case.get("case", {}).get("opening_date") or case.get("opened_at")
            opened_dt: Optional[datetime] = None
            if opened_raw:
                try:
                    opened_dt = datetime.strptime(str(opened_raw)[:10], "%Y-%m-%d")
                except ValueError:
                    pass
            timeline: list[dict] = []
            prev_dt: Optional[datetime] = None
            phase_order = ["D1_2", "D3", "D4", "D5", "D6", "D7", "D8"]
            for phase in phase_order:
                st = d_states.get(phase) or {}
                completed = st.get("status") == "completed"
                confirmed_raw = st.get("confirmed_at")
                days: Optional[int] = None
                if completed and confirmed_raw:
                    try:
                        cur_dt = datetime.strptime(confirmed_raw[:10], "%Y-%m-%d")
                        if phase == phase_order[0] and opened_dt is not None:
                            days = (cur_dt - opened_dt).days
                        elif prev_dt is not None:
                            days = (cur_dt - prev_dt).days
                        prev_dt = cur_dt
                    except ValueError:
                        prev_dt = None
                else:
                    prev_dt = None
                timeline.append({
                    "stage": phase,
                    "completed": completed,
                    "confirmed_at": confirmed_raw,
                    "days": days,
                })
            return timeline
        except Exception:
            logger.exception("[KPI] _compute_stage_timeline failed for %s", case_id)
            return []

    def _build_monthly_opened_closed(
        self,
        closed_cases: list[CaseSummary],
        active_cases: list[CaseSummary],
    ) -> list[dict[str, Any]]:
        """Return opened/closed counts per month for the last 6 calendar months."""
        now = self._utc_now()
        # Build list of 6 month boundaries, most recent last.
        months: list[tuple[int, int]] = []
        y, m = now.year, now.month
        for _ in range(6):
            months.append((y, m))
            m -= 1
            if m < 1:
                m = 12
                y -= 1
        months.reverse()  # oldest first

        all_cases = list(closed_cases) + list(active_cases)
        result: list[dict[str, Any]] = []
        for yr, mo in months:
            opened = sum(
                1 for c in all_cases
                if (d := self._to_utc(c.opening_date)) is not None  # type: ignore[arg-type]
                and d.year == yr and d.month == mo
            )
            closed = sum(
                1 for c in closed_cases
                if (d := self._to_utc(c.closure_date)) is not None  # type: ignore[arg-type]
                and d.year == yr and d.month == mo
            )
            label = datetime(yr, mo, 1).strftime("%Y-%m")
            result.append({"month": label, "opened": opened, "closed": closed})
        return result

    def _build_active_case_load(
        self,
        active_cases: list[CaseSummary],
    ) -> list[dict[str, Any]]:
        """Per-case active load summary for the frontend table."""
        now = self._utc_now()
        rows: list[dict[str, Any]] = []
        for c in active_cases:
            opening = self._to_utc(c.opening_date)  # type: ignore[arg-type]
            rows.append(
                {
                    "case_id": c.case_id,
                    "current_stage": self._translate_stage(c.current_stage)
                    or "Unknown",
                    "responsible_leader": c.responsible_leader,
                    "department": c.department,
                    "days_open": (now - opening).days if opening else None,
                }
            )
        return rows


__all__ = [
    "search_similar_cases",
    "search_cases_for_pattern_analysis",
    "search_cases_for_kpi",
    "search_active_cases_for_kpi",
    "search_case_by_id",
    "search_knowledge_base",
    "search_evidence",
    "KNOWLEDGE_MIN_SCORE",
    "KPITool",
]
