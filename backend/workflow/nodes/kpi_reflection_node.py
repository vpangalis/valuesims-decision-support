"""KPI reflection node for CoSolve.

Performs two layers of quality auditing on the KPIResult produced by KPINode:

1. **LLM interpretation** — generates a concise summary and key insights from
   the computed metrics.

2. **Semantic audit** — verifies:
   - Correct scope was used given the user's question.
   - render_hint matches the data complexity (a single number is not a bar_chart).
   - Suggestion chips guide the user toward a logical next scope
     (global → country → case).
   - responsible_leader and department are grounded in actual case data
     (not hallucinated).

User-facing language rules enforced:
- D-stage codes (D1, D2 … D8) must never appear in the summary or insights.
- Technical terms (Azure, LangGraph, index, node) must never appear.
"""

from __future__ import annotations

from pydantic import BaseModel

from langchain_openai import AzureChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from backend.workflow.models import (
    KPIInterpretation,
    KPIResult,
    KPIReflectionOutput,
    ReflectionVerdict,
)


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


class KPIReflectionNode:
    # Plain-language stage codes and banned technical terms — for use in audit prompts.
    _D_CODES = {"D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8", "D1_2", "D1_D2"}
    _BANNED_TECH_TERMS = {"azure", "langgraph", "index", "node"}

    def __init__(
        self,
        llm_client: AzureChatOpenAI,
        regeneration_llm_client: AzureChatOpenAI,
    ) -> None:
        self._llm_client = llm_client
        self._regeneration_llm_client = regeneration_llm_client

    def run(self, question: str, metrics: KPIResult) -> KPIReflectionOutput:
        # ── Step 1: Generate LLM interpretation ──────────────────────────
        interpretation = self._generate_interpretation(question, metrics)

        # ── Step 2: Semantic audit ────────────────────────────────────────
        audit = self._semantic_audit(question, metrics, interpretation)

        # ── Step 3: Regenerate if needed ─────────────────────────────────
        if audit.should_regenerate:
            interpretation = self._generate_interpretation(
                question,
                metrics,
                issues=audit.issues,
                use_regeneration_client=True,
            )

        # Build the verdict from the audit.
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

        completeness_score = self._compute_completeness(metrics, audit)
        verdict = ReflectionVerdict(
            schema_valid=bool(interpretation.summary and interpretation.insights),
            completeness_score=completeness_score,
            hallucination_risk=self._hallucination_risk(audit),
            should_regenerate=audit.should_regenerate,
            issues=all_issues,
        )

        return KPIReflectionOutput(
            kpi_interpretation=KPIInterpretation(
                summary=interpretation.summary,
                insights=interpretation.insights,
                metrics=metrics,
                render_hint=metrics.render_hint,
                scope_label=metrics.scope_label,
                suggestions=metrics.suggestions,
            ),
            kpi_reflection=verdict,
        )

    # ──────────────────────────────────────────────────────────────────────
    # Private helpers
    # ──────────────────────────────────────────────────────────────────────

    def _generate_interpretation(
        self,
        question: str,
        metrics: KPIResult,
        issues: list[str] | None = None,
        use_regeneration_client: bool = False,
    ) -> KPIInterpretationDraft:
        client = (
            self._regeneration_llm_client
            if use_regeneration_client
            else self._llm_client
        )
        issues_text = (
            f"\nYou must address these quality issues: {issues}" if issues else ""
        )
        return client.with_structured_output(KPIInterpretationDraft).invoke([
            SystemMessage(content=(
                "You are a performance analytics advisor for operations leadership. "
                "Your audience is plant managers and quality directors — never expose "
                "technical system names, database terms, or internal codes.\n\n"
                "RULES:\n"
                "- Never mention D1, D2, D3 … D8 codes. Use stage names only "
                "(e.g. 'Root Cause Analysis', 'Containment Actions').\n"
                "- Never use the words: Azure, LangGraph, index, node, vector.\n"
                "- Write in plain business language.\n"
                "- summary: one paragraph, ≤80 words.\n"
                "- insights: 2–4 concise bullet strings.\n\n"
                "Respond with ONLY this JSON — no other keys:\n"
                "{\n"
                '  "summary": "<concise KPI summary>",\n'
                '  "insights": ["insight 1", "insight 2"]\n'
                "}" + issues_text
            )),
            HumanMessage(content=(
                f"Scope: {metrics.scope_label}\n"
                f"Question: {question}\n"
                f"Metrics: {metrics.model_dump(exclude_none=True)}"
            )),
        ])

    def _semantic_audit(
        self,
        question: str,
        metrics: KPIResult,
        interpretation: KPIInterpretationDraft,
    ) -> KPISemanticAudit:
        # Build a plain-text description of the suggestions for the audit.
        suggestions_text = "\n".join(
            f"  {i+1}. {s}" for i, s in enumerate(metrics.suggestions)
        )

        return self._llm_client.with_structured_output(KPISemanticAudit).invoke([
            SystemMessage(content=(
                "You are a strict quality auditor for KPI analysis outputs. "
                "Respond with ONLY this JSON — no other keys:\n"
                "{\n"
                '  "scope_correct": true,\n'
                '  "scope_feedback": "<why scope is/is not correct>",\n'
                '  "render_hint_correct": true,\n'
                '  "render_hint_feedback": "<why render_hint is/is not appropriate>",\n'
                '  "suggestions_quality": "GOOD",\n'
                '  "suggestions_feedback": "<feedback on suggestions>",\n'
                '  "data_grounded": true,\n'
                '  "grounding_feedback": "<feedback on data grounding>",\n'
                '  "banned_terms_found": [],\n'
                '  "should_regenerate": false,\n'
                '  "issues": []\n'
                "}\n\n"
                "AUDIT RULES:\n"
                "scope_correct: true if the scope (global/country/case) matches what "
                "the user's question is asking for. E.g. a question about one country "
                "should use 'country' scope, not 'global'.\n"
                "render_hint_correct: 'gauge' for single-case elapsed time; "
                "'bar_chart' for country comparisons; 'table' for multi-metric "
                "global views; 'summary_text' for very sparse data. "
                "A single number should NOT be 'bar_chart'.\n"
                "suggestions_quality: 'GOOD' if the 3 suggestions guide the user "
                "toward a logical next scope (global → country → case). "
                "'NEEDS_IMPROVEMENT' if they are generic or repeat the same scope.\n"
                "data_grounded: true if responsible_leader and department are None "
                "(case not loaded) OR are non-empty strings. False if they appear "
                "hallucinated (e.g. contain technical jargon or clearly wrong data).\n"
                "banned_terms_found: list any of these that appear in the summary or "
                "insights: D1, D2, D3, D4, D5, D6, D7, D8, Azure, LangGraph, "
                "'index', 'node'.\n"
                "should_regenerate: true only if banned_terms_found is non-empty OR "
                "completeness_score < 0.5."
            )),
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

    def _compute_completeness(
        self, metrics: KPIResult, audit: KPISemanticAudit
    ) -> float:
        """Score 0.0–1.0 based on how many expected fields are populated and
        how clean the audit results are."""
        score = 0.5  # base
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

    def _hallucination_risk(self, audit: KPISemanticAudit) -> str:
        if not audit.data_grounded or audit.banned_terms_found:
            return "HIGH"
        if not audit.scope_correct or not audit.render_hint_correct:
            return "MEDIUM"
        return "LOW"


__all__ = ["KPIReflectionNode"]
