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


# DEPRECATED: not imported by any live node — superseded by plain dict returns.
class OperationalPayload(BaseModel):
    current_state: str
    current_state_recommendations: str
    next_state_preview: str
    supporting_cases: list[CaseSummary] = Field(default_factory=list)
    referenced_evidence: list[EvidenceSummary] = Field(default_factory=list)
    suggestions: list[dict[str, Any]] = Field(default_factory=list)


# DEPRECATED: not imported by any live node — superseded by plain dict returns.
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
    monthly_opened_closed: Optional[list[dict[str, Any]]] = None

    # ── Country-scope additions ────────────────────────────────────────────
    country_ranking: Optional[list[dict[str, Any]]] = None
    active_case_load: Optional[list[dict[str, Any]]] = None
    ytd_closed_count: Optional[int] = None
    global_avg_closure_days: Optional[float] = None

    # ── Global + country scope: status counts ─────────────────────────────
    open_count: Optional[int] = None
    in_progress_count: Optional[int] = None

    # ── Case-scope additions ───────────────────────────────────────────────
    stage_timeline: Optional[list[dict]] = None
    days_elapsed: Optional[int] = None
    gauge_label: Optional[str] = None
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



# DEPRECATED: not imported by any live node — superseded by plain dict returns.
class ReflectionVerdict(BaseModel):
    schema_valid: bool
    completeness_score: float = Field(ge=0.0, le=1.0)
    hallucination_risk: Literal["LOW", "MEDIUM", "HIGH"]
    should_regenerate: bool
    issues: list[str] = Field(default_factory=list)


# DEPRECATED: not imported by any live node — superseded by plain dict returns.
class ReflectionResult(BaseModel):
    quality_score: float = Field(ge=0.0, le=1.0)
    needs_escalation: bool
    reasoning_feedback: str


# DEPRECATED: not imported by any live node — superseded by plain dict returns.
class ContextNodeOutput(BaseModel):
    case_context: dict[str, Any] | None
    current_d_state: str | None


# DEPRECATED: not imported by any live node — superseded by plain dict returns.
class IntentNodeOutput(BaseModel):
    classification: IntentClassificationResult
    classification_low_confidence: bool = False



# DEPRECATED: not imported by any live node — superseded by plain dict returns.
class RouterNodeOutput(BaseModel):
    route: Literal[
        "OPERATIONAL_CASE",
        "SIMILARITY_SEARCH",
        "STRATEGY_ANALYSIS",
        "KPI_ANALYSIS",
    ]


# DEPRECATED: not imported by any live node — superseded by plain dict returns.
class OperationalNodeOutput(BaseModel):
    operational_draft: OperationalPayload


class OperationalReflectionAssessment(BaseModel):
    case_grounding: str  # GROUNDED | GENERIC | MIXED
    gap_detection: str  # SPECIFIC | VAGUE | MISSING
    next_state_relevance: str  # CONNECTED | DISCONNECTED | MISSING
    general_advice_flagged: str  # PRESENT_FLAGGED | PRESENT_UNFLAGGED | MISSING
    explore_next_quality: str  # SPECIFIC_MULTI_DOMAIN | GENERIC | INCOMPLETE | MISSING
    should_regenerate: bool
    issues: list[str]


# DEPRECATED: not imported by any live node — superseded by plain dict returns.
class OperationalReflectionOutput(BaseModel):
    operational_result: OperationalPayload
    operational_reflection: ReflectionResult


# DEPRECATED: not imported by any live node — superseded by plain dict returns.
class SimilarityPayload(BaseModel):
    summary: str
    supporting_cases: list[CaseSummary] = Field(default_factory=list)
    suggestions: list[dict[str, Any]] = Field(default_factory=list)


# DEPRECATED: not imported by any live node — superseded by plain dict returns.
class SimilarityNodeOutput(BaseModel):
    similarity_draft: SimilarityPayload


class SimilarityReflectionAssessment(BaseModel):
    case_specificity: str
    relevance_honesty: str
    pattern_quality: str
    general_advice_flagged: str
    explore_next_quality: str
    needs_regeneration: bool
    regeneration_focus: str | None = None


# DEPRECATED: not imported by any live node — superseded by plain dict returns.
class SimilarityReflectionOutput(BaseModel):
    similarity_result: SimilarityPayload
    similarity_reflection: SimilarityReflectionAssessment


# DEPRECATED: not imported by any live node — superseded by plain dict returns.
class StrategyPayload(BaseModel):
    summary: str
    strategic_recommendations: list[str] = Field(default_factory=list)
    supporting_cases: list[CaseSummary] = Field(default_factory=list)
    supporting_knowledge: list[KnowledgeSummary] = Field(default_factory=list)
    suggestions: list[dict[str, Any]] = Field(default_factory=list)


# DEPRECATED: not imported by any live node — superseded by plain dict returns.
class StrategyNodeOutput(BaseModel):
    strategy_draft: StrategyPayload


class StrategyReflectionAssessment(BaseModel):
    portfolio_breadth: str  # PASS | FAIL
    pattern_specificity: str  # PASS | FAIL
    weakness_strength: str  # PASS | FAIL
    knowledge_grounding: str  # PASS | FAIL
    explore_next_quality: str  # PASS | FAIL
    overall: str  # PASS | FAIL
    fail_section: str  # exact section label or NONE
    fail_reason: str  # one sentence or NONE


# DEPRECATED: not imported by any live node — superseded by plain dict returns.
class StrategyReflectionOutput(BaseModel):
    strategy_result: StrategyPayload
    strategy_reflection: ReflectionResult
    strategy_fail_section: str = ""
    strategy_fail_reason: str = ""


# DEPRECATED: not imported by any live node — superseded by plain dict returns.
class KPINodeOutput(BaseModel):
    kpi_metrics: KPIResult


# DEPRECATED: not imported by any live node — superseded by plain dict returns.
class KPIInterpretation(BaseModel):
    summary: str
    insights: list[str] = Field(default_factory=list)
    metrics: KPIResult
    # Forwarded from the computed KPIResult so the formatter has them in one place.
    render_hint: Literal["table", "bar_chart", "gauge", "summary_text"] = "table"
    scope_label: str = "Global"
    suggestions: list[str] = Field(default_factory=list)


# DEPRECATED: not imported by any live node — superseded by plain dict returns.
class KPIReflectionOutput(BaseModel):
    kpi_interpretation: KPIInterpretation
    kpi_reflection: ReflectionVerdict


class QuestionReadinessResult(BaseModel):
    ready: bool
    clarifying_question: str = ""


# DEPRECATED: not imported by any live node — superseded by plain dict returns.
class QuestionReadinessNodeOutput(BaseModel):
    question_ready: bool
    clarifying_question: str = ""


# DEPRECATED: not imported by any live node — superseded by plain dict returns.
class FinalResponsePayload(BaseModel):
    timestamp: str
    classification: IntentClassificationResult | None
    result: dict[str, Any]


# DEPRECATED: not imported by any live node — superseded by plain dict returns.
class ResponseFormatterOutput(BaseModel):
    final_response: FinalResponsePayload


__all__ = [
    "IntentClassificationResult",
    "OperationalPayload",
    "ScopeContext",
    "KPIResult",
    "ReflectionVerdict",
    "ReflectionResult",
    "ContextNodeOutput",
    "IntentNodeOutput",
    "RouterNodeOutput",
    "OperationalNodeOutput",
    "OperationalReflectionAssessment",
    "OperationalReflectionOutput",
    "SimilarityPayload",
    "SimilarityNodeOutput",
    "SimilarityReflectionAssessment",
    "SimilarityReflectionOutput",
    "StrategyPayload",
    "StrategyNodeOutput",
    "StrategyReflectionAssessment",
    "StrategyReflectionOutput",
    "KPINodeOutput",
    "KPIInterpretation",
    "KPIReflectionOutput",
    "QuestionReadinessResult",
    "QuestionReadinessNodeOutput",
    "FinalResponsePayload",
    "ResponseFormatterOutput",
]
