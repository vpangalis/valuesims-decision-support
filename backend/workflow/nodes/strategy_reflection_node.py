from __future__ import annotations

import json
import logging

from pydantic import BaseModel

from backend.infra.llm_logging_client import LoggedLanguageModelClient
from backend.workflow.models import (
    ReflectionResult,
    StrategyDraftPayload,
    StrategyReflectionOutput,
    StrategyResultPayload,
)

_debug_logger = logging.getLogger(__name__)


class StrategyReflectionAssessment(BaseModel):
    portfolio_breadth: str  # PASS | FAIL
    pattern_specificity: str  # PASS | FAIL
    weakness_strength: str  # PASS | FAIL
    knowledge_grounding: str  # PASS | FAIL
    explore_next_quality: str  # PASS | FAIL
    overall: str  # PASS | FAIL
    fail_section: str  # exact section label or NONE
    fail_reason: str  # one sentence or NONE


class StrategyReflectionNode:
    _REFLECTION_SYSTEM_PROMPT = """\
You are a quality auditor reviewing a strategic portfolio analysis response.
Your job is to catch reasoning failures, not check JSON schema.

Evaluate the draft response against these five criteria:

1. PORTFOLIO BREADTH
   Does the response reason across 2+ distinct cases with named case IDs?
   PASS: response mentions 2 or more distinct case IDs (e.g. TRM-xxx, TRM-yyy).
   FAIL: only one case ID is named, or no case IDs appear anywhere.

2. PATTERN SPECIFICITY
   Does [SYSTEMIC PATTERNS IDENTIFIED] name each pattern explicitly and back
   it with at least one specific case ID?
   PASS: each named pattern cites a case ID.
   FAIL: patterns are generic descriptions with no evidence from named cases.

3. WEAKNESS STRENGTH
   Does [ORGANISATIONAL WEAKNESSES] state weaknesses confidently when 2+ cases
   support them? Or does it hedge everything regardless of evidence?
   PASS: clear, confident statements when evidence (2+ cases) is present.
   FAIL: every weakness is hedged with "possibly" or "might" even when 2+ cases
         are cited, OR weaknesses are listed without any case evidence.

4. KNOWLEDGE GROUNDING
   Is at least one knowledge document referenced in the response?
   PASS if at least one knowledge doc is referenced.
   PASS also if no knowledge docs were available (retrieved list was empty).
   FAIL only if knowledge documents were present in context but completely ignored
   and the response makes no reference to any knowledge source.

5. EXPLORE NEXT QUALITY
   Does [WHAT TO EXPLORE NEXT] contain exactly 6 items with TEAM: and COSOLVE:
   prefix format, and are the questions at portfolio/fleet/org scope?
   PASS: 6 items, 3 starting with TEAM: and 3 starting with COSOLVE:, all at
         portfolio/fleet/org scope.
   FAIL: fewer than 6 items, incorrect prefix format, or questions are about a
         single incident rather than the portfolio.

Return ONLY this JSON object — no other keys, no prose:
{
  "portfolio_breadth": "PASS or FAIL",
  "pattern_specificity": "PASS or FAIL",
  "weakness_strength": "PASS or FAIL",
  "knowledge_grounding": "PASS or FAIL",
  "explore_next_quality": "PASS or FAIL",
  "overall": "PASS or FAIL",
  "fail_section": "exact section label such as [SYSTEMIC PATTERNS IDENTIFIED] or NONE",
  "fail_reason": "one sentence explaining the most important failure, or NONE"
}

overall must be FAIL if any individual criterion is FAIL.
overall must be PASS only if all five criteria are PASS.
fail_section: the first failing section label (using the exact bracket format), or NONE.
fail_reason: one sentence, or NONE.\
"""

    def __init__(
        self,
        llm_client: LoggedLanguageModelClient,
        regeneration_llm_client: LoggedLanguageModelClient,
    ) -> None:
        self._llm_client = llm_client
        self._regeneration_llm_client = regeneration_llm_client

    def run(
        self, question: str, draft: StrategyDraftPayload
    ) -> StrategyReflectionOutput:
        cases_summary = json.dumps(
            [c.model_dump(mode="json") for c in draft.supporting_cases],
            indent=2,
            default=str,
        )
        knowledge_summary = json.dumps(
            [k.model_dump(mode="json") for k in draft.supporting_knowledge],
            indent=2,
            default=str,
        )

        assessment = self._llm_client.complete_json(
            system_prompt=StrategyReflectionNode._REFLECTION_SYSTEM_PROMPT,
            user_prompt=(
                f"question: {question}\n\n"
                f"retrieved_cases: {cases_summary}\n\n"
                f"retrieved_knowledge: {knowledge_summary}\n\n"
                f"draft_response:\n{draft.summary}"
            ),
            response_model=StrategyReflectionAssessment,
            temperature=0.0,
            user_question=question,
        )

        _debug_logger.info("STRATEGY_REFLECTION: %s", assessment.model_dump())

        overall_pass = assessment.overall.upper() == "PASS"
        fail_section = (
            "" if assessment.fail_section.upper() == "NONE" else assessment.fail_section
        )
        fail_reason = (
            "" if assessment.fail_reason.upper() == "NONE" else assessment.fail_reason
        )

        quality_score = (
            1.0
            if overall_pass
            else sum(
                1.0
                for v in [
                    assessment.portfolio_breadth,
                    assessment.pattern_specificity,
                    assessment.weakness_strength,
                    assessment.knowledge_grounding,
                    assessment.explore_next_quality,
                ]
                if v.upper() == "PASS"
            )
            / 5.0
        )

        # Carry the summary and suggestions forward unchanged
        summary = draft.summary
        suggestions = list(draft.suggestions)

        return StrategyReflectionOutput(
            strategy_result=StrategyResultPayload(
                summary=summary,
                strategic_recommendations=[],
                supporting_cases=draft.supporting_cases,
                supporting_knowledge=draft.supporting_knowledge,
                suggestions=suggestions,
            ),
            strategy_reflection=ReflectionResult(
                quality_score=quality_score,
                needs_escalation=not overall_pass,
                reasoning_feedback=(
                    f"{fail_section}: {fail_reason}"
                    if fail_section
                    else "Strategy draft accepted."
                ),
            ),
            strategy_fail_section=fail_section,
            strategy_fail_reason=fail_reason,
        )


# Remove module-level prompt name — it now lives exclusively as
# StrategyReflectionNode._REFLECTION_SYSTEM_PROMPT.

__all__ = ["StrategyReflectionNode"]
