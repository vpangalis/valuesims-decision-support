from __future__ import annotations

import json
import logging

from backend.infra.llm_logging_client import LoggedLanguageModelClient
from backend.workflow.nodes.base_reflection_node import BaseReflectionNode
from backend.workflow.models import (
    ReflectionResult,
    StrategyPayload,
    StrategyReflectionAssessment,
    StrategyReflectionOutput,
)

_debug_logger = logging.getLogger(__name__)


class StrategyReflectionNode(BaseReflectionNode):
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

    # No regeneration prompt — strategy reflection does not regenerate.
    _REGENERATION_SYSTEM_PROMPT = ""

    def __init__(
        self,
        llm_client: LoggedLanguageModelClient,
        regeneration_llm_client: LoggedLanguageModelClient,
    ) -> None:
        super().__init__(
            llm_client=llm_client,
            regeneration_llm_client=regeneration_llm_client,
            reflection_prompt=self._REFLECTION_SYSTEM_PROMPT,
            regeneration_prompt=self._REGENERATION_SYSTEM_PROMPT,
            assessment_model=StrategyReflectionAssessment,
            score_fn=self._score,
            output_builder=self._build_output,
        )
        self._current_draft: StrategyPayload | None = None

    def _score(self, assessment: StrategyReflectionAssessment) -> float:
        overall_pass = assessment.overall.upper() == "PASS"
        if overall_pass:
            return 1.0
        return sum(
            1.0
            for v in [
                assessment.portfolio_breadth,
                assessment.pattern_specificity,
                assessment.weakness_strength,
                assessment.knowledge_grounding,
                assessment.explore_next_quality,
            ]
            if v.upper() == "PASS"
        ) / 5.0

    def _build_output(self, draft_text: str, assessment: StrategyReflectionAssessment) -> dict:
        draft = self._current_draft
        overall_pass = assessment.overall.upper() == "PASS"
        fail_section = (
            "" if assessment.fail_section.upper() == "NONE" else assessment.fail_section
        )
        fail_reason = (
            "" if assessment.fail_reason.upper() == "NONE" else assessment.fail_reason
        )
        return StrategyReflectionOutput(
            strategy_result=StrategyPayload(
                summary=draft_text,
                strategic_recommendations=[],
                supporting_cases=draft.supporting_cases,
                supporting_knowledge=draft.supporting_knowledge,
                suggestions=list(draft.suggestions),
            ),
            strategy_reflection=ReflectionResult(
                quality_score=self._score(assessment),
                needs_escalation=not overall_pass,
                reasoning_feedback=(
                    f"{fail_section}: {fail_reason}"
                    if fail_section
                    else "Strategy draft accepted."
                ),
            ),
            strategy_fail_section=fail_section,
            strategy_fail_reason=fail_reason,
        ).model_dump()

    def run(self, question: str, draft: StrategyPayload) -> StrategyReflectionOutput:
        """Reflect on the strategy draft.

        Unique logic: user_prompt includes retrieved_cases and retrieved_knowledge
        context beyond the base class format; no regeneration path exists for
        strategy reflection.
        """
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
        self._current_draft = draft
        try:
            assessment = self._llm_client.complete_json(
                system_prompt=self._reflection_prompt,
                user_prompt=(
                    f"question: {question}\n\n"
                    f"retrieved_cases: {cases_summary}\n\n"
                    f"retrieved_knowledge: {knowledge_summary}\n\n"
                    f"draft_response:\n{draft.summary}"
                ),
                response_model=self._assessment_model,
                temperature=0.0,
                user_question=question,
            )
            _debug_logger.info("STRATEGY_REFLECTION: %s", assessment.model_dump())
            result_dict = self._build_output(draft.summary, assessment)
            return StrategyReflectionOutput.model_validate(result_dict)
        finally:
            self._current_draft = None


__all__ = ["StrategyReflectionNode"]
