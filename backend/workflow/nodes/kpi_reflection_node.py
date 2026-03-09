"""KPI reflection node for CoSolve.

Performs two layers of quality auditing on the KPIResult produced by KPINode:

1. **LLM interpretation** -- generates a concise summary and key insights from
   the computed metrics.

2. **Semantic audit** -- verifies:
   - Correct scope was used given the user's question.
   - render_hint matches the data complexity (a single number is not a bar_chart).
   - Suggestion chips guide the user toward a logical next scope
     (global -> country -> case).
   - responsible_leader and department are grounded in actual case data
     (not hallucinated).

User-facing language rules enforced:
- D-stage codes (D1, D2 ... D8) must never appear in the summary or insights.
- Technical terms (Azure, LangGraph, index, node) must never appear.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel

from backend.state import IncidentGraphState
from backend.llm import get_llm
from langchain_openai import AzureChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from backend.prompts import (
    KPI_REFLECTION_STEP1_PROMPT,
    KPI_REFLECTION_STEP2_PROMPT,
)
from backend.workflow.models import KPIResult

_logger = logging.getLogger(__name__)


class KPIInterpretationDraft(BaseModel):
    summary: str
    insights: list[str]


class KPISemanticAudit(BaseModel):
    scope_correct: bool
    scope_feedback: str
    render_hint_correct: bool
    render_hint_feedback: str
    suggestions_quality: str  # "GOOD" | "NEEDS_IMPROVEMENT"
    suggestions_feedback: str
    data_grounded: bool
    grounding_feedback: str
    banned_terms_found: list[str]
    should_regenerate: bool
    issues: list[str]


def kpi_reflection_node(state: IncidentGraphState) -> dict:
    """Two-layer quality audit on KPI metrics and interpretation."""
    question = state.get("question", "")
    kpi_metrics_raw = state.get("kpi_metrics") or {}

    # Reconstruct KPIResult from the dict in state
    metrics = KPIResult.model_validate(kpi_metrics_raw)

    llm = get_llm("reasoning", 0.0)
    regen_llm = get_llm("reasoning", 0.0)

    # Step 1: Generate LLM interpretation
    interpretation = _generate_interpretation(llm, question, metrics)

    # Step 2: Semantic audit
    audit = _semantic_audit(llm, question, metrics, interpretation)

    # Step 3: Regenerate if needed
    if audit.should_regenerate:
        interpretation = _generate_interpretation(
            regen_llm, question, metrics, issues=audit.issues,
        )

    # Build the verdict from the audit
    all_issues = audit.issues[:]
    if not audit.scope_correct:
        all_issues.append(f"Scope issue: {audit.scope_feedback}")
    if not audit.render_hint_correct:
        all_issues.append(f"Render hint issue: {audit.render_hint_feedback}")
    if audit.suggestions_quality != "GOOD":
        all_issues.append(f"Suggestions issue: {audit.suggestions_feedback}")
    if not audit.data_grounded:
        all_issues.append(f"Grounding issue: {audit.grounding_feedback}")
    if audit.banned_terms_found:
        all_issues.append(
            f"Banned terms in output: {', '.join(audit.banned_terms_found)}"
        )

    completeness_score = _compute_completeness(metrics, audit)

    return {
        "kpi_interpretation": {
            "summary": interpretation.summary,
            "insights": interpretation.insights,
            "metrics": metrics.model_dump(mode="json"),
            "render_hint": metrics.render_hint,
            "scope_label": metrics.scope_label,
            "suggestions": metrics.suggestions,
        },
        "kpi_reflection": {
            "schema_valid": bool(interpretation.summary and interpretation.insights),
            "completeness_score": completeness_score,
            "hallucination_risk": _hallucination_risk(audit),
            "should_regenerate": audit.should_regenerate,
            "issues": all_issues,
        },
        "_last_node": "kpi_reflection_node",
    }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _generate_interpretation(
    llm: AzureChatOpenAI,
    question: str,
    metrics: KPIResult,
    issues: list[str] | None = None,
) -> KPIInterpretationDraft:
    issues_text = (
        f"\nYou must address these quality issues: {issues}" if issues else ""
    )
    return llm.with_structured_output(KPIInterpretationDraft).invoke([
        SystemMessage(content=KPI_REFLECTION_STEP1_PROMPT + issues_text),
        HumanMessage(content=(
            f"Scope: {metrics.scope_label}\n"
            f"Question: {question}\n"
            f"Metrics: {metrics.model_dump(exclude_none=True)}"
        )),
    ])


def _semantic_audit(
    llm: AzureChatOpenAI,
    question: str,
    metrics: KPIResult,
    interpretation: KPIInterpretationDraft,
) -> KPISemanticAudit:
    suggestions_text = "\n".join(
        f"  {i+1}. {s}" for i, s in enumerate(metrics.suggestions)
    )
    return llm.with_structured_output(KPISemanticAudit).invoke([
        SystemMessage(content=KPI_REFLECTION_STEP2_PROMPT),
        HumanMessage(content=(
            f"User question: {question}\n"
            f"Scope used: {metrics.scope}\n"
            f"render_hint used: {metrics.render_hint}\n"
            f"Suggestions:\n{suggestions_text}\n"
            f"responsible_leader: {metrics.responsible_leader!r}\n"
            f"department: {metrics.department!r}\n"
            f"Summary produced: {interpretation.summary}\n"
            f"Insights produced: {interpretation.insights}"
        )),
    ])


def _compute_completeness(metrics: KPIResult, audit: KPISemanticAudit) -> float:
    score = 0.5
    if metrics.scope in ("global", "country"):
        if metrics.avg_closure_days_ytd is not None:
            score += 0.1
        if metrics.total_cases_closed_ytd is not None:
            score += 0.1
        if metrics.d_stage_distribution:
            score += 0.1
    elif metrics.scope == "case":
        if metrics.days_elapsed is not None:
            score += 0.15
        if metrics.current_stage:
            score += 0.1
    if audit.scope_correct:
        score += 0.05
    if audit.render_hint_correct:
        score += 0.05
    if metrics.suggestions:
        score += 0.05
    return min(round(score, 2), 1.0)


def _hallucination_risk(audit: KPISemanticAudit) -> str:
    if not audit.data_grounded or audit.banned_terms_found:
        return "HIGH"
    if not audit.scope_correct or not audit.render_hint_correct:
        return "MEDIUM"
    return "LOW"


