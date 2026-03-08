from __future__ import annotations

from langchain_openai import AzureChatOpenAI
from backend.workflow.nodes.base_reflection_node import BaseReflectionNode
from backend.prompts import SIMILARITY_REFLECTION_SYSTEM_PROMPT, SIMILARITY_REGENERATION_SYSTEM_PROMPT
from backend.workflow.nodes.node_parsing_utils import extract_similarity_suggestions
from backend.workflow.models import (
    SimilarityPayload,
    SimilarityReflectionAssessment,
    SimilarityReflectionOutput,
)


class SimilarityReflectionNode(BaseReflectionNode):

    _REFLECTION_SYSTEM_PROMPT = SIMILARITY_REFLECTION_SYSTEM_PROMPT

    _REGENERATION_SYSTEM_PROMPT = SIMILARITY_REGENERATION_SYSTEM_PROMPT

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
