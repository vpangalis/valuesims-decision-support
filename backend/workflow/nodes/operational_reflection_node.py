from __future__ import annotations

from langchain_openai import AzureChatOpenAI
from backend.workflow.nodes.base_reflection_node import BaseReflectionNode
from backend.workflow.nodes.node_parsing_utils import (
    extract_suggestions,
    is_new_problem_question,
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

    _REFLECTION_SYSTEM_PROMPT = """\
You are a quality auditor reviewing an operational advisory response before it reaches the team.
Your job is not to check JSON schema. Your job is to catch reasoning failures.

Evaluate the draft response against these five criteria:

1. CASE GROUNDING
   Does [CURRENT STATE] reference actual data from the case history provided?
   Or does it give advice that would apply to any case regardless of content?
   Score: GROUNDED | GENERIC | MIXED

2. GAP DETECTION QUALITY
   Does [GAPS IN PREVIOUS STATES] identify real weaknesses in the case entries?
   Or does it produce placeholder text like "ensure D3 is complete"?
   Score: SPECIFIC | VAGUE | MISSING

3. NEXT STATE RELEVANCE
   Does [NEXT STATE PREVIEW] connect logically to what was found in the case?
   Or is it a generic list of D-state activities?
   Score: CONNECTED | DISCONNECTED | MISSING

4. GENERAL ADVICE FLAGGED
   Is [GENERAL ADVICE] present and does it carry the ⚠️ warning prefix?
   Score: PRESENT_FLAGGED | PRESENT_UNFLAGGED | MISSING

5. EXPLORE NEXT QUALITY
   Is [WHAT TO EXPLORE NEXT] present with BOTH subsections:
   (a) "Questions to ask your team right now" containing at least two bullet-point
       questions grounded in the actual case data, AND
   (b) "Questions to ask CoSolve" containing all four icon-prefixed questions
       (🔍 similar cases, ⚙️ operational, 📊 strategic, 📈 KPI)?
   Are all six questions specific to this case, or are they generic?
   Score: SPECIFIC_MULTI_DOMAIN | GENERIC | INCOMPLETE | MISSING
   SPECIFIC_MULTI_DOMAIN: both subsections present, all six questions case-specific
   GENERIC: questions present in both subsections but not grounded in case data
   INCOMPLETE: fewer than six questions total, or one of the two subsections missing
   MISSING: [WHAT TO EXPLORE NEXT] section absent entirely

Return ONLY this JSON:
{
  "case_grounding": "GROUNDED|GENERIC|MIXED",
  "gap_detection": "SPECIFIC|VAGUE|MISSING",
  "next_state_relevance": "CONNECTED|DISCONNECTED|MISSING",
  "general_advice_flagged": "PRESENT_FLAGGED|PRESENT_UNFLAGGED|MISSING",
  "explore_next_quality": "SPECIFIC_MULTI_DOMAIN|GENERIC|INCOMPLETE|MISSING",
  "should_regenerate": false,
  "issues": []
}

Rules for should_regenerate:
Set true if case_grounding is GENERIC, or gap_detection is MISSING,
or next_state_relevance is DISCONNECTED or MISSING,
or general_advice_flagged is MISSING,
or explore_next_quality is MISSING or INCOMPLETE.

issues: list every specific criterion that failed, empty list if all pass.\
"""
    _REGENERATION_SYSTEM_PROMPT = """\
You are a senior operational problem-solving advisor. A previous draft advisory response
was rejected by the quality auditor for the following reasons:

{issues}

Rewrite the advisory response in full, correcting all identified failures.
Your rewritten response must follow exactly the same structure as the original:

  [CURRENT STATE]
  [GAPS IN PREVIOUS STATES]
  [NEXT STATE PREVIEW]
  [GENERAL ADVICE]
  ⚠️ General advice not specific to this case:
  [WHAT TO EXPLORE NEXT]

Every section is mandatory. [CURRENT STATE] and [GAPS] must reference actual case data.
[GENERAL ADVICE] must carry the ⚠️ warning prefix.
[WHAT TO EXPLORE NEXT] must contain BOTH:
  - "Questions to ask your team right now" with two case-grounded bullet points
  - "Questions to ask CoSolve" with all four icon-prefixed questions
    (🔍 similar cases, ⚙️ operational deep-dive, 📊 strategic view, 📈 KPI & trends)
    all grounded in this case.
Section order is mandatory: [CURRENT STATE], [GAPS IN PREVIOUS STATES],
[NEXT STATE PREVIEW], [GENERAL ADVICE], [WHAT TO EXPLORE NEXT].
[WHAT TO EXPLORE NEXT] must be the final section; nothing may appear after it.

Return plain text only. No JSON.\
"""

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
