from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from backend.retrieval.models import CaseSummary, EvidenceSummary, KnowledgeSummary


class IntentClassificationResult(BaseModel):
    intent: Literal[
        "OPERATIONAL_CASE",
        "SIMILARITY_SEARCH",
        "STRATEGY_ANALYSIS",
        "KPI_ANALYSIS",
    ]
    scope: Literal["LOCAL", "COUNTRY", "GLOBAL"]
    confidence: float = Field(ge=0.0, le=1.0)


class OperationalGuidance(BaseModel):
    current_state: str
    current_state_recommendations: str
    next_state_preview: str
    supporting_cases: list[CaseSummary] = Field(default_factory=list)
    referenced_evidence: list[EvidenceSummary] = Field(default_factory=list)
    suggestions: list[dict[str, Any]] = Field(default_factory=list)


class OperationalReasoningDraft(BaseModel):
    current_state: str
    current_state_recommendations: str
    next_state_preview: str


class ScopeContext(BaseModel):
    country: Optional[str] = None

    @field_validator("country")
    @classmethod
    def normalize_country(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        return normalized


class KPIResult(BaseModel):
    """Computed KPI metrics produced by KPITool.get_kpis().

    Contains the raw metric values plus rendering hints and follow-up
    suggestions for the frontend chips.
    """

    scope: Literal["global", "country", "case"] = "global"
    scope_label: str = "Global"
    render_hint: Literal["table", "bar_chart", "gauge", "summary_text"] = "table"
    suggestions: list[str] = Field(default_factory=list)

    # ── Common metrics (global + country) ──────────────────────────────────
    total_cases_opened_ytd: Optional[int] = None
    total_cases_closed_ytd: Optional[int] = None
    avg_closure_days_ytd: Optional[float] = None
    avg_closure_days_rolling_12m: Optional[float] = None
    recurrence_rate: Optional[float] = None
    first_closure_rate: Optional[float] = None
    overdue_count: Optional[int] = None
    overdue_pct: Optional[float] = None
    d_stage_distribution: Optional[dict[str, int]] = None
    avg_days_per_stage: Optional[dict[str, float]] = None

    # ── Country-scope additions ────────────────────────────────────────────
    country_ranking: Optional[list[dict[str, Any]]] = None
    active_case_load: Optional[list[dict[str, Any]]] = None
    ytd_closed_count: Optional[int] = None
    global_avg_closure_days: Optional[float] = None

    # ── Case-scope additions ───────────────────────────────────────────────
    days_elapsed: Optional[int] = None
    category_benchmark_days: Optional[float] = None
    current_stage: Optional[str] = None
    responsible_leader: Optional[str] = None
    department: Optional[str] = None
    days_stuck_at_current_stage: Optional[int] = None
    similar_cases_avg_resolution_days: Optional[float] = None

    # ── Backward-compat fields (kept so old code that reads these still works) ─
    total_closed_cases: Optional[int] = None
    min_closure_days: Optional[int] = None
    avg_closure_days: Optional[float] = None
    max_closure_days: Optional[int] = None


# Backward-compatibility alias so callers that still import KPIMetrics keep working.
KPIMetrics = KPIResult


class ReflectionVerdict(BaseModel):
    schema_valid: bool
    completeness_score: float = Field(ge=0.0, le=1.0)
    hallucination_risk: Literal["LOW", "MEDIUM", "HIGH"]
    should_regenerate: bool
    issues: list[str] = Field(default_factory=list)


class ReflectionResult(BaseModel):
    quality_score: float = Field(ge=0.0, le=1.0)
    needs_escalation: bool
    reasoning_feedback: str


class ContextNodeOutput(BaseModel):
    case_context: dict[str, Any] | None
    current_d_state: str | None


class IntentNodeOutput(BaseModel):
    classification: IntentClassificationResult


class IntentReflectionOutput(BaseModel):
    classification: IntentClassificationResult
    intent_reflection: ReflectionVerdict


class RouterNodeOutput(BaseModel):
    route: Literal[
        "OPERATIONAL_CASE",
        "SIMILARITY_SEARCH",
        "STRATEGY_ANALYSIS",
        "KPI_ANALYSIS",
    ]


class OperationalDraftPayload(BaseModel):
    current_state: str
    current_state_recommendations: str
    next_state_preview: str
    supporting_cases: list[CaseSummary] = Field(default_factory=list)
    referenced_evidence: list[EvidenceSummary] = Field(default_factory=list)
    suggestions: list[dict[str, Any]] = Field(default_factory=list)


class OperationalNodeOutput(BaseModel):
    operational_draft: OperationalDraftPayload


class OperationalReflectionOutput(BaseModel):
    operational_result: OperationalGuidance
    operational_reflection: ReflectionResult


class SimilarityDraftPayload(BaseModel):
    summary: str
    supporting_cases: list[CaseSummary] = Field(default_factory=list)
    suggestions: list[dict[str, Any]] = Field(default_factory=list)


class SimilarityNodeOutput(BaseModel):
    similarity_draft: SimilarityDraftPayload


class SimilarityResultPayload(BaseModel):
    summary: str
    supporting_cases: list[CaseSummary] = Field(default_factory=list)
    suggestions: list[dict[str, Any]] = Field(default_factory=list)


class SimilarityReflectionAssessment(BaseModel):
    case_specificity: str
    relevance_honesty: str
    pattern_quality: str
    general_advice_flagged: str
    explore_next_quality: str
    needs_regeneration: bool
    regeneration_focus: str | None = None


class SimilarityReflectionOutput(BaseModel):
    similarity_result: SimilarityResultPayload
    similarity_reflection: SimilarityReflectionAssessment


class StrategyDraftPayload(BaseModel):
    summary: str
    supporting_cases: list[CaseSummary] = Field(default_factory=list)
    supporting_knowledge: list[KnowledgeSummary] = Field(default_factory=list)
    suggestions: list[dict[str, Any]] = Field(default_factory=list)


class StrategyNodeOutput(BaseModel):
    strategy_draft: StrategyDraftPayload


class StrategyResultPayload(BaseModel):
    summary: str
    strategic_recommendations: list[str] = Field(default_factory=list)
    supporting_cases: list[CaseSummary] = Field(default_factory=list)
    supporting_knowledge: list[KnowledgeSummary] = Field(default_factory=list)
    suggestions: list[dict[str, Any]] = Field(default_factory=list)


class StrategyReflectionOutput(BaseModel):
    strategy_result: StrategyResultPayload
    strategy_reflection: ReflectionResult
    strategy_fail_section: str = ""
    strategy_fail_reason: str = ""


class KPINodeOutput(BaseModel):
    kpi_metrics: KPIResult


class KPIInterpretation(BaseModel):
    summary: str
    insights: list[str] = Field(default_factory=list)
    metrics: KPIResult
    # Forwarded from the computed KPIResult so the formatter has them in one place.
    render_hint: Literal["table", "bar_chart", "gauge", "summary_text"] = "table"
    scope_label: str = "Global"
    suggestions: list[str] = Field(default_factory=list)


class KPIReflectionOutput(BaseModel):
    kpi_interpretation: KPIInterpretation
    kpi_reflection: ReflectionVerdict


class FinalResponsePayload(BaseModel):
    timestamp: str
    classification: IntentClassificationResult | None
    result: dict[str, Any]


class ResponseFormatterOutput(BaseModel):
    final_response: FinalResponsePayload


__all__ = [
    "IntentClassificationResult",
    "OperationalGuidance",
    "OperationalReasoningDraft",
    "ScopeContext",
    "KPIResult",
    "KPIMetrics",
    "ReflectionVerdict",
    "ReflectionResult",
    "ContextNodeOutput",
    "IntentNodeOutput",
    "IntentReflectionOutput",
    "RouterNodeOutput",
    "OperationalDraftPayload",
    "OperationalNodeOutput",
    "OperationalReflectionOutput",
    "SimilarityDraftPayload",
    "SimilarityNodeOutput",
    "SimilarityResultPayload",
    "SimilarityReflectionAssessment",
    "SimilarityReflectionOutput",
    "StrategyDraftPayload",
    "StrategyNodeOutput",
    "StrategyResultPayload",
    "StrategyReflectionOutput",
    "KPINodeOutput",
    "KPIInterpretation",
    "KPIReflectionOutput",
    "FinalResponsePayload",
    "ResponseFormatterOutput",
]
