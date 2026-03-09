from __future__ import annotations

import json
import logging

from backend.state import IncidentGraphState
from backend.llm import get_llm
from langchain_openai import AzureChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from backend.workflow.models import StrategyReflectionAssessment
from backend.prompts import STRATEGY_REFLECTION_SYSTEM_PROMPT, STRATEGY_REGENERATION_SYSTEM_PROMPT

_logger = logging.getLogger(__name__)


def strategy_reflection_node(state: IncidentGraphState) -> dict:
    """Reflect on the strategy draft with structured quality assessment."""
    draft = state.get("strategy_draft") or {}
    question = state.get("question", "")
    draft_text = draft.get("summary", "")

    # Build context from supporting data
    supporting_cases = draft.get("supporting_cases", [])
    supporting_knowledge = draft.get("supporting_knowledge", [])
    cases_summary = json.dumps(supporting_cases, indent=2, default=str)
    knowledge_summary = json.dumps(supporting_knowledge, indent=2, default=str)

    llm = get_llm("reasoning", 0.0)

    try:
        assessment = llm.with_structured_output(StrategyReflectionAssessment).invoke([
            SystemMessage(content=STRATEGY_REFLECTION_SYSTEM_PROMPT),
            HumanMessage(content=(
                f"question: {question}\n\n"
                f"retrieved_cases: {cases_summary}\n\n"
                f"retrieved_knowledge: {knowledge_summary}\n\n"
                f"draft_response:\n{draft_text}"
            )),
        ])
        _logger.info("STRATEGY_REFLECTION: %s", str(assessment))

        overall_pass = assessment.overall.upper() == "PASS"
        score = _score(assessment)

        fail_section = (
            "" if assessment.fail_section.upper() == "NONE" else assessment.fail_section
        )
        fail_reason = (
            "" if assessment.fail_reason.upper() == "NONE" else assessment.fail_reason
        )

        return {
            "strategy_result": {
                "summary": draft_text,
                "strategic_recommendations": [],
                "supporting_cases": supporting_cases,
                "supporting_knowledge": supporting_knowledge,
                "suggestions": list(draft.get("suggestions", [])),
            },
            "strategy_reflection": {
                "quality_score": score,
                "needs_escalation": not overall_pass,
                "reasoning_feedback": (
                    f"{fail_section}: {fail_reason}"
                    if fail_section
                    else "Strategy draft accepted."
                ),
            },
            "strategy_fail_section": fail_section,
            "strategy_fail_reason": fail_reason,
            "_last_node": "strategy_reflection_node",
        }

    except Exception as exc:
        _logger.exception("strategy_reflection_node failed: %s", exc)
        return {
            "strategy_result": draft,
            "_last_node": "strategy_reflection_node",
        }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _score(assessment: StrategyReflectionAssessment) -> float:
    overall_pass = assessment.overall.upper() == "PASS"
    if overall_pass:
        return 1.0
    return (
        sum(
            1.0
            for v in [
                assessment.portfolio_breadth,
                assessment.pattern_specificity,
                assessment.weakness_strength,
                assessment.knowledge_grounding,
                assessment.explore_next_quality,
            ]
            if v.upper() == "PASS"
        )
        / 5.0
    )


