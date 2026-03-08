from __future__ import annotations

from langchain_openai import AzureChatOpenAI
from backend.workflow.nodes.base_reflection_node import BaseReflectionNode
from backend.workflow.nodes.node_parsing_utils import (
    extract_suggestions,
    is_new_problem_question,
)
from backend.prompts import (
    OPERATIONAL_REFLECTION_SYSTEM_PROMPT,
    OPERATIONAL_REGENERATION_SYSTEM_PROMPT,
)
from backend.workflow.models import (
    OperationalPayload,
    OperationalReflectionAssessment,
    OperationalReflectionOutput,
    ReflectionResult,
)


class OperationalReflectionNode(BaseReflectionNode):
    _NEW_PROBLEM_NO_CASE_MARKERS = (
        "[SIMILAR CASES — CHECK FIRST]",
        "[IF THIS IS A NEW PROBLEM — HOW TO START]",
    )

    _REFLECTION_SYSTEM_PROMPT = OPERATIONAL_REFLECTION_SYSTEM_PROMPT
    _REGENERATION_SYSTEM_PROMPT = OPERATIONAL_REGENERATION_SYSTEM_PROMPT

    def _is_new_problem_bypass(
        self, question: str, draft_text: str, case_loaded: bool
    ) -> bool:
        """Return True when the response used the NEW PROBLEM DETECTION path
        and reflection should be skipped entirely."""
        if case_loaded:
            return False
        if is_new_problem_question(question, case_id=""):
            return True
        if any(
            m in draft_text
            for m in OperationalReflectionNode._NEW_PROBLEM_NO_CASE_MARKERS
        ):
            return True
        return False

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
            assessment_model=OperationalReflectionAssessment,
            score_fn=self._score,
            output_builder=self._build_output,
        )
        self._current_draft: OperationalPayload | None = None

    def _score(self, assessment: OperationalReflectionAssessment) -> float:
        g = {"GROUNDED": 1.0, "MIXED": 0.6, "GENERIC": 0.0}.get(
            assessment.case_grounding, 0.5
        )
        d = {"SPECIFIC": 1.0, "VAGUE": 0.5, "MISSING": 0.0}.get(
            assessment.gap_detection, 0.5
        )
        n = {"CONNECTED": 1.0, "DISCONNECTED": 0.3, "MISSING": 0.0}.get(
            assessment.next_state_relevance, 0.5
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
        return max(0.0, min(1.0, (g + d + n + a + e) / 5.0))

    def _build_output(
        self, draft_text: str, assessment: OperationalReflectionAssessment
    ) -> dict:
        draft = self._current_draft
        needs_escalation = (
            assessment.case_grounding == "GENERIC"
            or assessment.gap_detection == "MISSING"
            or assessment.next_state_relevance in ("DISCONNECTED", "MISSING")
            or assessment.general_advice_flagged == "MISSING"
            or assessment.explore_next_quality in ("MISSING", "INCOMPLETE")
        )
        regenerated = draft_text != draft.current_state_recommendations
        return OperationalReflectionOutput(
            operational_result=OperationalPayload(
                current_state=draft.current_state,
                current_state_recommendations=draft_text,
                next_state_preview="" if regenerated else draft.next_state_preview,
                supporting_cases=draft.supporting_cases,
                referenced_evidence=draft.referenced_evidence,
                suggestions=extract_suggestions(draft_text),
            ),
            operational_reflection=ReflectionResult(
                quality_score=self._score(assessment),
                needs_escalation=needs_escalation,
                reasoning_feedback=(
                    "; ".join(assessment.issues)
                    if assessment.issues
                    else "Operational draft accepted."
                ),
            ),
        ).model_dump()

    def run(
        self, question: str, draft: OperationalPayload
    ) -> OperationalReflectionOutput:
        case_loaded = bool(
            draft.current_state and draft.current_state != "No case loaded"
        )
        if self._is_new_problem_bypass(
            question, draft.current_state_recommendations, case_loaded
        ):
            return OperationalReflectionOutput(
                operational_result=OperationalPayload(
                    current_state=draft.current_state,
                    current_state_recommendations=draft.current_state_recommendations,
                    next_state_preview=draft.next_state_preview,
                    supporting_cases=draft.supporting_cases,
                    referenced_evidence=draft.referenced_evidence,
                    suggestions=extract_suggestions(
                        draft.current_state_recommendations
                    ),
                ),
                operational_reflection=ReflectionResult(
                    quality_score=1.0,
                    needs_escalation=False,
                    reasoning_feedback="New problem detection — reflection bypassed.",
                ),
            )
        self._current_draft = draft
        try:
            result_dict = super().run(
                draft_text=draft.current_state_recommendations,
                question=question,
                case_id="",
            )
            return OperationalReflectionOutput.model_validate(result_dict)
        finally:
            self._current_draft = None


__all__ = ["OperationalReflectionNode"]
