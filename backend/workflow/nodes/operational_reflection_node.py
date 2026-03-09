from __future__ import annotations

import logging

from backend.state import IncidentGraphState
from backend.llm import get_llm
from langchain_openai import AzureChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from backend.workflow.nodes.node_parsing_utils import (
    extract_suggestions,
    is_new_problem_question,
)
from backend.prompts import (
    OPERATIONAL_REFLECTION_SYSTEM_PROMPT,
    OPERATIONAL_REGENERATION_SYSTEM_PROMPT,
)
from backend.workflow.models import OperationalReflectionAssessment

_logger = logging.getLogger(__name__)
_REGENERATION_THRESHOLD: float = 0.65
_NEW_PROBLEM_NO_CASE_MARKERS = (
    "[SIMILAR CASES \u2014 CHECK FIRST]",
    "[IF THIS IS A NEW PROBLEM \u2014 HOW TO START]",
)


def operational_reflection_node(state: IncidentGraphState) -> dict:
    """Critically assess quality of the operational draft."""
    draft = state.get("operational_draft") or {}
    question = state.get("question", "")
    draft_text = draft.get("current_state_recommendations", "")
    current_state = draft.get("current_state", "")

    case_loaded = bool(current_state and current_state != "No case loaded")

    # Bypass reflection for new-problem-detection path
    if _is_new_problem_bypass(question, draft_text, case_loaded):
        return {
            "operational_result": {
                "current_state": current_state,
                "current_state_recommendations": draft_text,
                "next_state_preview": draft.get("next_state_preview", ""),
                "supporting_cases": draft.get("supporting_cases", []),
                "referenced_evidence": draft.get("referenced_evidence", []),
                "suggestions": extract_suggestions(draft_text),
            },
            "operational_reflection": {
                "quality_score": 1.0,
                "needs_escalation": False,
                "reasoning_feedback": "New problem detection \u2014 reflection bypassed.",
            },
            "_last_node": "operational_reflection_node",
        }

    llm = get_llm("reasoning", 0.0)
    regen_llm = get_llm("reasoning", 0.0)

    try:
        assessment = llm.with_structured_output(OperationalReflectionAssessment).invoke([
            SystemMessage(content=OPERATIONAL_REFLECTION_SYSTEM_PROMPT),
            HumanMessage(content=f"question: {question}\n\ndraft_response:\n{draft_text}"),
        ])

        score = _score(assessment)
        final_draft = draft_text

        if score < _REGENERATION_THRESHOLD:
            _logger.info(
                "operational_reflection_node: score %.3f below threshold %.3f \u2014 triggering regeneration.",
                score, _REGENERATION_THRESHOLD,
            )
            final_draft = regen_llm.invoke([
                SystemMessage(content=OPERATIONAL_REGENERATION_SYSTEM_PROMPT),
                HumanMessage(content=f"Question: {question}"),
            ]).content

        needs_escalation = (
            assessment.case_grounding == "GENERIC"
            or assessment.gap_detection == "MISSING"
            or assessment.next_state_relevance in ("DISCONNECTED", "MISSING")
            or assessment.general_advice_flagged == "MISSING"
            or assessment.explore_next_quality in ("MISSING", "INCOMPLETE")
        )
        regenerated = final_draft != draft_text

        return {
            "operational_result": {
                "current_state": current_state,
                "current_state_recommendations": final_draft,
                "next_state_preview": "" if regenerated else draft.get("next_state_preview", ""),
                "supporting_cases": draft.get("supporting_cases", []),
                "referenced_evidence": draft.get("referenced_evidence", []),
                "suggestions": extract_suggestions(final_draft),
            },
            "operational_reflection": {
                "quality_score": score,
                "needs_escalation": needs_escalation,
                "reasoning_feedback": (
                    "; ".join(assessment.issues)
                    if assessment.issues
                    else "Operational draft accepted."
                ),
            },
            "_last_node": "operational_reflection_node",
        }

    except Exception as exc:
        _logger.exception("operational_reflection_node failed: %s", exc)
        return {
            "operational_result": draft,
            "_last_node": "operational_reflection_node",
        }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _score(assessment: OperationalReflectionAssessment) -> float:
    g = {"GROUNDED": 1.0, "MIXED": 0.6, "GENERIC": 0.0}.get(assessment.case_grounding, 0.5)
    d = {"SPECIFIC": 1.0, "VAGUE": 0.5, "MISSING": 0.0}.get(assessment.gap_detection, 0.5)
    n = {"CONNECTED": 1.0, "DISCONNECTED": 0.3, "MISSING": 0.0}.get(assessment.next_state_relevance, 0.5)
    a = {"PRESENT_FLAGGED": 1.0, "PRESENT_UNFLAGGED": 0.6, "MISSING": 0.0}.get(assessment.general_advice_flagged, 0.5)
    e = {"SPECIFIC_MULTI_DOMAIN": 1.0, "GENERIC": 0.5, "INCOMPLETE": 0.3, "MISSING": 0.0}.get(
        assessment.explore_next_quality, 0.5
    )
    return max(0.0, min(1.0, (g + d + n + a + e) / 5.0))


def _is_new_problem_bypass(question: str, draft_text: str, case_loaded: bool) -> bool:
    if case_loaded:
        return False
    if is_new_problem_question(question, case_id=""):
        return True
    if any(m in draft_text for m in _NEW_PROBLEM_NO_CASE_MARKERS):
        return True
    return False


