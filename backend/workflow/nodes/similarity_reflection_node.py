from __future__ import annotations

import logging

from backend.infra.llm_logging_client import LoggedLanguageModelClient
from backend.workflow.nodes.base_reflection_node import BaseReflectionNode
from backend.workflow.nodes.node_parsing_utils import extract_similarity_suggestions
from backend.workflow.models import (
    SimilarityPayload,
    SimilarityReflectionAssessment,
    SimilarityReflectionOutput,
)

_debug_logger = logging.getLogger(__name__)


class SimilarityReflectionNode(BaseReflectionNode):
    _REFLECTION_SYSTEM_PROMPT = """\
You are a quality auditor reviewing a similarity analysis response.
Your job is to catch reasoning failures, not check JSON schema.

Evaluate against these five criteria:

1. CASE SPECIFICITY
   Does [SIMILAR CASES FOUND] reference actual retrieved cases by ID \
with specific failure details?
   Or does it describe cases vaguely without referencing actual data?
   Score: SPECIFIC | VAGUE | MISSING

2. RELEVANCE HONESTY
   Does the response honestly rate match strength (STRONG/PARTIAL/WEAK)?
   Or does it treat all retrieved cases as equally or falsely relevant?
   Score: HONEST | FORCED | MISSING

3. PATTERN QUALITY
   Does [PATTERNS ACROSS CASES] identify a genuine cross-case insight?
   Or is it a restatement of individual summaries or forced connection?
   Score: GENUINE | RESTATEMENT | MISSING

4. GENERAL ADVICE FLAGGED
   Is [GENERAL ADVICE] present with the \u26a0\ufe0f warning prefix?
   Score: PRESENT_FLAGGED | PRESENT_UNFLAGGED | MISSING

5. EXPLORE NEXT QUALITY
   Is [WHAT TO EXPLORE NEXT] present with both subsections?
   Are all six questions specific to the retrieved cases?
   Score: SPECIFIC_MULTI_DOMAIN | GENERIC | INCOMPLETE | MISSING

Return ONLY this JSON:
{
  "case_specificity": "SPECIFIC|VAGUE|MISSING",
  "relevance_honesty": "HONEST|FORCED|MISSING",
  "pattern_quality": "GENUINE|RESTATEMENT|MISSING",
  "general_advice_flagged": "PRESENT_FLAGGED|PRESENT_UNFLAGGED|MISSING",
  "explore_next_quality": "SPECIFIC_MULTI_DOMAIN|GENERIC|INCOMPLETE|MISSING",
  "needs_regeneration": true,
  "regeneration_focus": "one sentence if needs_regeneration true, else null"
}

needs_regeneration = true if ANY of:
  - case_specificity is MISSING
  - relevance_honesty is FORCED
  - pattern_quality is MISSING
  - general_advice_flagged is MISSING
  - explore_next_quality is MISSING or GENERIC\
"""

    _REGENERATION_SYSTEM_PROMPT = """\
The previous response failed on this specific dimension: {regeneration_focus}

Rewrite ONLY the failing section. Keep all other sections unchanged.
Return the complete response with all five sections in mandatory order:
[SIMILAR CASES FOUND], [PATTERNS ACROSS CASES], \
[WHAT THIS MEANS FOR YOUR INVESTIGATION], [GENERAL ADVICE], \
[WHAT TO EXPLORE NEXT]

If rewriting [SIMILAR CASES FOUND]: reference every retrieved case \
by ID with its match rating (STRONG/PARTIAL/WEAK) and specific details.
If rewriting [WHAT TO EXPLORE NEXT]: all six questions must reference \
specific case IDs or findings — no generic questions.

Original response: {draft}
Retrieved cases: {formatted_cases}
Question: {question}\
"""

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
            assessment_model=SimilarityReflectionAssessment,
            score_fn=self._score,
            output_builder=self._build_output,
        )
        self._current_draft: SimilarityPayload | None = None

    def _score(self, assessment: SimilarityReflectionAssessment) -> float:
        c = {"SPECIFIC": 1.0, "VAGUE": 0.5, "MISSING": 0.0}.get(
            assessment.case_specificity, 0.5
        )
        r = {"HONEST": 1.0, "FORCED": 0.3, "MISSING": 0.0}.get(
            assessment.relevance_honesty, 0.5
        )
        p = {"GENUINE": 1.0, "RESTATEMENT": 0.5, "MISSING": 0.0}.get(
            assessment.pattern_quality, 0.5
        )
        a = {"PRESENT_FLAGGED": 1.0, "PRESENT_UNFLAGGED": 0.6, "MISSING": 0.0}.get(
            assessment.general_advice_flagged, 0.5
        )
        e = {
            "SPECIFIC_MULTI_DOMAIN": 1.0,
            "GENERIC": 0.5,
            "INCOMPLETE": 0.3,
            "MISSING": 0.0,
        }.get(assessment.explore_next_quality, 0.5)
        return max(0.0, min(1.0, (c + r + p + a + e) / 5.0))

    def _build_output(
        self, draft_text: str, assessment: SimilarityReflectionAssessment
    ) -> dict:
        draft = self._current_draft
        suggestions = extract_similarity_suggestions(draft_text)
        return SimilarityReflectionOutput(
            similarity_result=SimilarityPayload(
                summary=draft_text,
                supporting_cases=draft.supporting_cases,
                suggestions=suggestions,
            ),
            similarity_reflection=assessment,
        ).model_dump()

    def run(
        self, question: str, draft: SimilarityPayload
    ) -> SimilarityReflectionOutput:
        self._current_draft = draft
        try:
            result_dict = super().run(
                draft_text=draft.summary,
                question=question,
                case_id="",
            )
            return SimilarityReflectionOutput.model_validate(result_dict)
        finally:
            self._current_draft = None


__all__ = ["SimilarityReflectionNode"]
