from __future__ import annotations

import logging

from backend.state import IncidentGraphState
from backend.llm import get_llm
from langchain_openai import AzureChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from backend.prompts import SIMILARITY_REFLECTION_SYSTEM_PROMPT, SIMILARITY_REGENERATION_SYSTEM_PROMPT
from backend.workflow.nodes.node_parsing_utils import extract_similarity_suggestions
from backend.workflow.models import SimilarityReflectionAssessment

_logger = logging.getLogger(__name__)
_REGENERATION_THRESHOLD: float = 0.65


def similarity_reflection_node(state: IncidentGraphState) -> dict:
    """Critically assess quality of the similarity draft."""
    draft = state.get("similarity_draft") or {}
    question = state.get("question", "")
    draft_text = draft.get("summary", "")

    llm = get_llm("reasoning", 0.0)
    regen_llm = get_llm("reasoning", 0.0)

    try:
        assessment = llm.with_structured_output(SimilarityReflectionAssessment).invoke([
            SystemMessage(content=SIMILARITY_REFLECTION_SYSTEM_PROMPT),
            HumanMessage(content=f"question: {question}\n\ndraft_response:\n{draft_text}"),
        ])

        score = _score(assessment)
        final_draft = draft_text

        if score < _REGENERATION_THRESHOLD:
            _logger.info(
                "similarity_reflection_node: score %.3f below threshold %.3f \u2014 triggering regeneration.",
                score, _REGENERATION_THRESHOLD,
            )
            final_draft = regen_llm.invoke([
                SystemMessage(content=SIMILARITY_REGENERATION_SYSTEM_PROMPT),
                HumanMessage(content=f"Question: {question}"),
            ]).content

        feedback = (
            assessment.regeneration_focus
            if assessment.needs_regeneration and assessment.regeneration_focus
            else "Similarity draft accepted."
        )

        return {
            "similarity_result": {
                "summary": final_draft,
                "supporting_cases": draft.get("supporting_cases", []),
                "suggestions": extract_similarity_suggestions(final_draft),
            },
            "similarity_reflection": {
                "case_specificity": assessment.case_specificity,
                "relevance_honesty": assessment.relevance_honesty,
                "pattern_quality": assessment.pattern_quality,
                "general_advice_flagged": assessment.general_advice_flagged,
                "explore_next_quality": assessment.explore_next_quality,
                "needs_regeneration": assessment.needs_regeneration,
                "regeneration_focus": feedback,
            },
            "_last_node": "similarity_reflection_node",
        }

    except Exception as exc:
        _logger.exception("similarity_reflection_node failed: %s", exc)
        return {
            "similarity_result": draft,
            "_last_node": "similarity_reflection_node",
        }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _score(assessment: SimilarityReflectionAssessment) -> float:
    c = {"GROUNDED": 1.0, "GENERIC": 0.3, "MISSING": 0.0}.get(assessment.case_specificity, 0.5)
    r = {"HONEST": 1.0, "INFLATED": 0.3, "MISSING": 0.0}.get(assessment.relevance_honesty, 0.5)
    p = {"GENUINE": 1.0, "FORCED": 0.3, "MISSING": 0.0}.get(assessment.pattern_quality, 0.5)
    a = {"PRESENT_FLAGGED": 1.0, "PRESENT_UNFLAGGED": 0.6, "MISSING": 0.0}.get(
        assessment.general_advice_flagged, 0.5
    )
    e = {"SPECIFIC_MULTI_DOMAIN": 1.0, "GENERIC": 0.5, "INCOMPLETE": 0.3, "MISSING": 0.0}.get(
        assessment.explore_next_quality, 0.5
    )
    return max(0.0, min(1.0, (c + r + p + a + e) / 5.0))


