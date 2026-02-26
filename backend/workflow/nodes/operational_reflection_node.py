from __future__ import annotations

import logging

from pydantic import BaseModel

from backend.infra.llm_logging_client import LoggedLanguageModelClient
from backend.workflow.nodes.operational_node import OperationalNode

_debug_logger = logging.getLogger(__name__)
from backend.workflow.models import (
    OperationalDraftPayload,
    OperationalGuidance,
    OperationalReflectionOutput,
    ReflectionResult,
)


class OperationalReflectionAssessment(BaseModel):
    case_grounding: str  # GROUNDED | GENERIC | MIXED
    gap_detection: str  # SPECIFIC | VAGUE | MISSING
    next_state_relevance: str  # CONNECTED | DISCONNECTED | MISSING
    general_advice_flagged: str  # PRESENT_FLAGGED | PRESENT_UNFLAGGED | MISSING
    explore_next_quality: str  # SPECIFIC_MULTI_DOMAIN | GENERIC | INCOMPLETE | MISSING
    should_regenerate: bool
    issues: list[str]


class OperationalReflectionNode:
    _NEW_PROBLEM_NO_CASE_MARKERS = (
        "[SIMILAR CASES — CHECK FIRST]",
        "[IF THIS IS A NEW PROBLEM — HOW TO START]",
    )

    @staticmethod
    def _is_new_problem_bypass(
        question: str, draft_text: str, case_loaded: bool
    ) -> bool:
        """Return True when the response used the NEW PROBLEM DETECTION path
        and reflection should be skipped entirely."""
        if case_loaded:
            return False
        q = question.lower()
        # keyword match
        if any(kw in q for kw in OperationalNode._NEW_PROBLEM_KEYWORDS):
            return True
        # short question + problem-domain word
        if len(q.split()) <= 10 and any(
            w in q for w in ("problem", "issue", "fault", "failure")
        ):
            return True
        # the draft itself already uses the alternate section markers
        if any(
            m in draft_text
            for m in OperationalReflectionNode._NEW_PROBLEM_NO_CASE_MARKERS
        ):
            return True
        return False

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
   Is [GENERAL ADVICE] present and does it carry the \u26a0\ufe0f warning prefix?
   Score: PRESENT_FLAGGED | PRESENT_UNFLAGGED | MISSING

5. EXPLORE NEXT QUALITY
   Is [WHAT TO EXPLORE NEXT] present with BOTH subsections:
   (a) "Questions to ask your team right now" containing at least two bullet-point
       questions grounded in the actual case data, AND
   (b) "Questions to ask CoSolve" containing all four icon-prefixed questions
       (\U0001f50d similar cases, \u2699\ufe0f operational, \U0001f4ca strategic, \U0001f4c8 KPI)?
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
  \u26a0\ufe0f General advice not specific to this case:
  [WHAT TO EXPLORE NEXT]

Every section is mandatory. [CURRENT STATE] and [GAPS] must reference actual case data.
[GENERAL ADVICE] must carry the \u26a0\ufe0f warning prefix.
[WHAT TO EXPLORE NEXT] must contain BOTH:
  - "Questions to ask your team right now" with two case-grounded bullet points
  - "Questions to ask CoSolve" with all four icon-prefixed questions
    (\U0001f50d similar cases, \u2699\ufe0f operational deep-dive, \U0001f4ca strategic view, \U0001f4c8 KPI & trends)
    all grounded in this case.
Section order is mandatory: [CURRENT STATE], [GAPS IN PREVIOUS STATES],
[NEXT STATE PREVIEW], [GENERAL ADVICE], [WHAT TO EXPLORE NEXT].
[WHAT TO EXPLORE NEXT] must be the final section; nothing may appear after it.

Return plain text only. No JSON.\
"""

    def __init__(
        self,
        llm_client: LoggedLanguageModelClient,
        regeneration_llm_client: LoggedLanguageModelClient,
    ) -> None:
        self._llm_client = llm_client
        self._regeneration_llm_client = regeneration_llm_client

    def run(
        self, question: str, draft: OperationalDraftPayload
    ) -> OperationalReflectionOutput:
        # Bypass reflection entirely for new-problem / no-case responses so
        # the auditor does not fail them for missing active-case sections.
        case_loaded = bool(
            draft.current_state and draft.current_state != "No case loaded"
        )
        if OperationalReflectionNode._is_new_problem_bypass(
            question, draft.current_state_recommendations, case_loaded
        ):
            result = OperationalGuidance(
                current_state=draft.current_state,
                current_state_recommendations=draft.current_state_recommendations,
                next_state_preview=draft.next_state_preview,
                supporting_cases=draft.supporting_cases,
                referenced_evidence=draft.referenced_evidence,
                suggestions=OperationalNode._extract_suggestions(
                    draft.current_state_recommendations
                ),
            )
            return OperationalReflectionOutput(
                operational_result=result,
                operational_reflection=ReflectionResult(
                    quality_score=1.0,
                    needs_escalation=False,
                    reasoning_feedback="New problem detection — reflection bypassed.",
                ),
            )

        assessment = self._llm_client.complete_json(
            system_prompt=OperationalReflectionNode._REFLECTION_SYSTEM_PROMPT,
            user_prompt=(
                f"question: {question}\n\n"
                f"draft_response:\n{draft.current_state_recommendations}"
            ),
            response_model=OperationalReflectionAssessment,
            temperature=0.0,
            user_question=question,
        )

        grounding_score = {"GROUNDED": 1.0, "MIXED": 0.6, "GENERIC": 0.0}.get(
            assessment.case_grounding, 0.5
        )
        gap_score = {"SPECIFIC": 1.0, "VAGUE": 0.5, "MISSING": 0.0}.get(
            assessment.gap_detection, 0.5
        )
        next_score = {"CONNECTED": 1.0, "DISCONNECTED": 0.3, "MISSING": 0.0}.get(
            assessment.next_state_relevance, 0.5
        )
        advice_score = {
            "PRESENT_FLAGGED": 1.0,
            "PRESENT_UNFLAGGED": 0.6,
            "MISSING": 0.0,
        }.get(assessment.general_advice_flagged, 0.5)
        explore_score = {
            "SPECIFIC_MULTI_DOMAIN": 1.0,
            "GENERIC": 0.5,
            "INCOMPLETE": 0.3,
            "MISSING": 0.0,
        }.get(assessment.explore_next_quality, 0.5)
        quality_score = max(
            0.0,
            min(
                1.0,
                (
                    grounding_score
                    + gap_score
                    + next_score
                    + advice_score
                    + explore_score
                )
                / 5.0,
            ),
        )

        needs_escalation = (
            assessment.case_grounding == "GENERIC"
            or assessment.gap_detection == "MISSING"
            or assessment.next_state_relevance in ("DISCONNECTED", "MISSING")
            or assessment.general_advice_flagged == "MISSING"
            or assessment.explore_next_quality in ("MISSING", "INCOMPLETE")
        )

        recommendations = draft.current_state_recommendations
        next_preview = draft.next_state_preview
        if assessment.should_regenerate:
            issues_text = (
                "\n".join(f"- {issue}" for issue in assessment.issues)
                if assessment.issues
                else "- General quality below threshold."
            )
            regenerated_text = self._regeneration_llm_client.complete_text(
                system_prompt=OperationalReflectionNode._REGENERATION_SYSTEM_PROMPT.format(
                    issues=issues_text
                ),
                user_prompt=(
                    f"question: {question}\n\n"
                    f"original_draft:\n{draft.current_state_recommendations}"
                ),
                temperature=0.1,
                user_question=question,
            )
            recommendations = regenerated_text
            # FIX 1: keep next_state_preview empty so it is not rendered as a
            # separate field while still appearing inline in the full text.
            next_preview = ""

        result = OperationalGuidance(
            current_state=draft.current_state,
            current_state_recommendations=recommendations,
            next_state_preview=next_preview,
            supporting_cases=draft.supporting_cases,
            referenced_evidence=draft.referenced_evidence,
            suggestions=OperationalNode._extract_suggestions(recommendations),
        )
        return OperationalReflectionOutput(
            operational_result=result,
            operational_reflection=ReflectionResult(
                quality_score=quality_score,
                needs_escalation=needs_escalation,
                reasoning_feedback=(
                    "; ".join(assessment.issues)
                    if assessment.issues
                    else "Operational draft accepted."
                ),
            ),
        )


__all__ = ["OperationalReflectionNode"]
