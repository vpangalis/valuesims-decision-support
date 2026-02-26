from __future__ import annotations

import json
import logging

from backend.infra.llm_logging_client import LoggedLanguageModelClient
from backend.workflow.models import (
    SimilarityDraftPayload,
    SimilarityReflectionAssessment,
    SimilarityReflectionOutput,
    SimilarityResultPayload,
)

_debug_logger = logging.getLogger(__name__)


class SimilarityReflectionNode:
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
        self._llm_client = llm_client
        self._regeneration_llm_client = regeneration_llm_client

    def run(
        self, question: str, draft: SimilarityDraftPayload
    ) -> SimilarityReflectionOutput:
        cases_summary = json.dumps(
            [c.model_dump(mode="json") for c in draft.supporting_cases],
            indent=2,
            default=str,
        )

        assessment = self._llm_client.complete_json(
            system_prompt=SimilarityReflectionNode._REFLECTION_SYSTEM_PROMPT,
            user_prompt=(
                f"question: {question}\n"
                f"retrieved_cases_summary: {cases_summary}\n"
                f"draft_response: {draft.summary}"
            ),
            response_model=SimilarityReflectionAssessment,
            temperature=0.0,
            user_question=question,
        )

        _debug_logger.info("SIMILARITY_REFLECTION: %s", assessment.model_dump())

        summary = draft.summary
        suggestions = draft.suggestions

        if assessment.needs_regeneration:
            formatted_cases = json.dumps(
                [c.model_dump(mode="json") for c in draft.supporting_cases],
                indent=2,
                default=str,
            )
            regen_prompt = SimilarityReflectionNode._REGENERATION_SYSTEM_PROMPT.format(
                regeneration_focus=assessment.regeneration_focus or "",
                draft=draft.summary,
                formatted_cases=formatted_cases,
                question=question,
            )
            summary = self._regeneration_llm_client.complete_text(
                system_prompt=regen_prompt,
                user_prompt=f"Question: {question}",
                temperature=0.1,
                user_question=question,
            )
            # Re-extract suggestions from regenerated text
            from backend.workflow.nodes.similarity_node import SimilarityNode

            suggestions = SimilarityNode._extract_suggestions(summary)

        return SimilarityReflectionOutput(
            similarity_result=SimilarityResultPayload(
                summary=summary,
                supporting_cases=draft.supporting_cases,
                suggestions=suggestions,
            ),
            similarity_reflection=assessment,
        )


# Remove module-level prompt names — they now live exclusively as
# SimilarityReflectionNode class attributes.

__all__ = ["SimilarityReflectionNode"]
