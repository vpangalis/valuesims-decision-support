from __future__ import annotations

from langchain_openai import AzureChatOpenAI
from backend.workflow.nodes.base_reflection_node import BaseReflectionNode
from backend.workflow.nodes.node_parsing_utils import extract_similarity_suggestions
from backend.workflow.models import (
    SimilarityPayload,
    SimilarityReflectionAssessment,
    SimilarityReflectionOutput,
)


class SimilarityReflectionNode(BaseReflectionNode):

    _REFLECTION_SYSTEM_PROMPT = """You are a quality auditor reviewing a similarity analysis response before
it reaches the team. Your job is to catch reasoning failures, not check
JSON schema.

The response was produced by an agent instructed to find and evaluate
closed cases similar to the current problem, identify genuine cross-case
patterns, explain what the findings mean for the investigation, include
general guidance clearly flagged as non-specific, and provide specific
case-grounded follow-up questions.

Evaluate the draft against these five criteria:

1. CASE SPECIFICITY
   Does [SIMILAR CASES FOUND] reference actual retrieved case IDs with
   honest STRONG / PARTIAL / WEAK match ratings?
   GROUNDED: at least one case cited by ID with a match rating and a
     clear reason for the rating.
   GENERIC: cases mentioned by theme or component only, no case IDs.
   MISSING: [SIMILAR CASES FOUND] absent or contains no cases.

2. RELEVANCE HONESTY
   Are match ratings accurate? A weak match must not be rated STRONG.
   If no cases were retrieved, does the response say so explicitly
   rather than inventing similarity?
   HONEST: ratings consistent with the stated reasons.
   INFLATED: a case rated STRONG but the reason is superficial or vague.
   MISSING: no match ratings present anywhere in the response.

3. PATTERN QUALITY
   Does [PATTERNS ACROSS CASES] name a genuine pattern backed by 2+
   cases, OR explicitly state that no genuine pattern exists?
   GENUINE: pattern named and backed by 2+ case IDs, OR honest
     statement that no pattern exists across the retrieved cases.
   FORCED: pattern claimed but only one case supports it, or the
     connection is superficial.
   MISSING: [PATTERNS ACROSS CASES] section absent entirely.

4. GENERAL ADVICE FLAGGED
   Is [GENERAL ADVICE] present as its own section starting with \u26a0\ufe0f?
   PRESENT_FLAGGED: section exists and starts with \u26a0\ufe0f.
   PRESENT_UNFLAGGED: section exists but \u26a0\ufe0f prefix is absent.
   MISSING: [GENERAL ADVICE] absent or merged into another section.

5. EXPLORE NEXT QUALITY
   Is [WHAT TO EXPLORE NEXT] present with BOTH:
   (a) "Questions to ask your team right now" \u2014 2+ bullet questions
       grounded in the retrieved cases, AND
   (b) "Questions to ask CoSolve" \u2014 3+ icon-prefixed questions
       (\u2699\ufe0f operational, \U0001f4ca strategic, \U0001f4c8 KPI or \U0001f50d dig deeper)?
   SPECIFIC_MULTI_DOMAIN: both subsections present, questions reference
     actual case details or failure patterns.
   GENERIC: questions present but could apply to any investigation.
   INCOMPLETE: one subsection missing, or fewer than 4 questions total.
   MISSING: [WHAT TO EXPLORE NEXT] section absent entirely.

Set needs_regeneration: true if ANY of the following:
  - case_specificity is GENERIC or MISSING
  - relevance_honesty is INFLATED or MISSING
  - pattern_quality is FORCED or MISSING
  - general_advice_flagged is MISSING
  - explore_next_quality is MISSING or INCOMPLETE

If needs_regeneration is true, set regeneration_focus to a one-sentence
description of the most important failure to correct.
If needs_regeneration is false, set regeneration_focus to null.

Return ONLY this JSON \u2014 no prose, no markdown:
{
  "case_specificity": "GROUNDED|GENERIC|MISSING",
  "relevance_honesty": "HONEST|INFLATED|MISSING",
  "pattern_quality": "GENUINE|FORCED|MISSING",
  "general_advice_flagged": "PRESENT_FLAGGED|PRESENT_UNFLAGGED|MISSING",
  "explore_next_quality": "SPECIFIC_MULTI_DOMAIN|GENERIC|INCOMPLETE|MISSING",
  "needs_regeneration": false,
  "regeneration_focus": null
}
"""

    _REGENERATION_SYSTEM_PROMPT = """You are a senior failure analysis expert. A previous similarity analysis
response was rejected by the quality auditor for the following reason:

{issues}

Rewrite the response in full, correcting the identified failure.
Your rewritten response must follow exactly the same structure:

  [SIMILAR CASES FOUND]
  [PATTERNS ACROSS CASES]
  [WHAT THIS MEANS FOR YOUR INVESTIGATION]
  [GENERAL ADVICE]
  [WHAT TO EXPLORE NEXT]

Requirements:
- Every case citation must use [Country][Site] case_id format.
  Never invent case IDs or country/site values.
- Match ratings (STRONG / PARTIAL / WEAK) must be honest and justified.
- [PATTERNS ACROSS CASES] must be genuine \u2014 backed by 2+ cases \u2014 or
  must explicitly state no genuine pattern exists.
- [GENERAL ADVICE] must be its own section and must start with \u26a0\ufe0f.
- [WHAT TO EXPLORE NEXT] must contain BOTH:
    "Questions to ask your team right now" (2 bullet questions grounded
    in the retrieved cases)
    "Questions to ask CoSolve" (3+ icon-prefixed questions:
    \u2699\ufe0f operational, \U0001f4ca strategic, \U0001f4c8 KPI or \U0001f50d dig deeper)
- Target 300\u2013400 words. All five sections required regardless of count.
- Return plain text only. No JSON. No markdown beyond section labels.
"""

    def __init__(
        self,
        llm_client: AzureChatOpenAI,
        regeneration_llm_client: AzureChatOpenAI,
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
        c = {"GROUNDED": 1.0, "GENERIC": 0.3, "MISSING": 0.0}.get(
            assessment.case_specificity, 0.5
        )
        r = {"HONEST": 1.0, "INFLATED": 0.3, "MISSING": 0.0}.get(
            assessment.relevance_honesty, 0.5
        )
        p = {"GENUINE": 1.0, "FORCED": 0.3, "MISSING": 0.0}.get(
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
        feedback = (
            assessment.regeneration_focus
            if assessment.needs_regeneration and assessment.regeneration_focus
            else "Similarity draft accepted."
        )
        return SimilarityReflectionOutput(
            similarity_result=SimilarityPayload(
                summary=draft_text,
                supporting_cases=draft.supporting_cases,
                suggestions=extract_similarity_suggestions(draft_text),
            ),
            similarity_reflection=SimilarityReflectionAssessment(
                case_specificity=assessment.case_specificity,
                relevance_honesty=assessment.relevance_honesty,
                pattern_quality=assessment.pattern_quality,
                general_advice_flagged=assessment.general_advice_flagged,
                explore_next_quality=assessment.explore_next_quality,
                needs_regeneration=assessment.needs_regeneration,
                regeneration_focus=feedback,
            ),
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
