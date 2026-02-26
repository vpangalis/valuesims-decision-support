"""question_readiness_node.py

Runs immediately after intent classification and before any reasoning node.
Its single responsibility: assess whether the system has enough context to
give a meaningful, grounded answer.

If the question can be answered → ready=True, graph proceeds normally.
If context is insufficient    → ready=False, clarifying_question is set and
                                 the graph exits early with that question.
"""

from __future__ import annotations

import logging

from backend.infra.llm_logging_client import LoggedLanguageModelClient
from backend.workflow.models import QuestionReadinessResult, QuestionReadinessNodeOutput

_logger = logging.getLogger(__name__)

# ── Standard 6 pivot suggestions shown whenever we ask for clarification ──────
_STANDARD_SUGGESTIONS: list[dict] = [
    {
        "label": "What should we focus on?",
        "question": "What should we focus on right now?",
    },
    {
        "label": "Performance overview",
        "question": "How is our overall incident resolution performance?",
    },
    {
        "label": "Similar past cases",
        "question": "Have we dealt with a problem like this before?",
    },
    {
        "label": "Recurring failures",
        "question": "What are the most recurring failure types we face?",
    },
    {
        "label": "Open cases by area",
        "question": "Which areas have the most open cases right now?",
    },
    {
        "label": "How long to resolve?",
        "question": "How long do cases typically take to resolve?",
    },
]


class QuestionReadinessNode:
    """Assess whether available context is sufficient to answer the question."""

    _SYSTEM_PROMPT = (
        "You are a context readiness assessor for an industrial incident decision-support system. "
        "Your only job is to decide whether the system has enough context to give a meaningful, "
        "grounded answer to the user's question. "
        "Return strict JSON only — no explanation, no markdown."
    )

    def __init__(self, llm_client: LoggedLanguageModelClient) -> None:
        self._llm_client = llm_client

    def run(
        self,
        question: str,
        intent: str,
        case_id: str | None,
        case_context: dict | None,
    ) -> QuestionReadinessNodeOutput:
        case_loaded = bool(case_id and str(case_id).strip())
        case_status = "none"
        if case_loaded and isinstance(case_context, dict):
            case_status = str(case_context.get("case_status", "open"))

        user_prompt = (
            "Assess whether the question can be answered meaningfully with the available context.\n"
            "Return ONLY this JSON:\n"
            '{"ready": true, "clarifying_question": ""}\n\n'
            "=== READINESS RULES ===\n"
            "Set ready=true if ANY of the following apply:\n"
            "  • intent is STRATEGY_ANALYSIS (always portfolio-level, no single case needed)\n"
            "  • intent is KPI_ANALYSIS (metrics are computed from the full case database)\n"
            "  • intent is SIMILARITY_SEARCH (can search historical cases without a loaded case)\n"
            "  • intent is OPERATIONAL_CASE AND a case is currently loaded\n\n"
            "Set ready=false ONLY if:\n"
            "  • intent is OPERATIONAL_CASE AND case_loaded is false\n"
            "    AND the question clearly refers to the current, active, or specific case\n\n"
            "=== CLARIFYING QUESTION RULES (only when ready=false) ===\n"
            "Write a single question as a helpful, warm colleague would.\n"
            "Rules for the clarifying question:\n"
            "  • Plain language — no technical terms, no jargon\n"
            "  • Must NOT mention: intent, node, classification, routing, system, pipeline\n"
            "  • Must end with a suggestion to load or open a case if that is what is missing\n"
            "  • Maximum 2 sentences\n"
            "If ready=true, clarifying_question MUST be an empty string.\n\n"
            "=== CONTEXT ===\n"
            f"intent: {intent}\n"
            f"case_loaded: {'true' if case_loaded else 'false'}\n"
            f"case_status: {case_status}\n"
            f"question: {question}"
        )

        try:
            result = self._llm_client.complete_json(
                system_prompt=self._SYSTEM_PROMPT,
                user_prompt=user_prompt,
                response_model=QuestionReadinessResult,
                temperature=0.0,
                max_tokens=200,
                user_question=question,
            )
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "QuestionReadinessNode: LLM call failed — defaulting to ready=True. Error: %s",
                exc,
            )
            result = QuestionReadinessResult(ready=True, clarifying_question="")

        return QuestionReadinessNodeOutput(
            question_ready=result.ready,
            clarifying_question=result.clarifying_question if not result.ready else None,
            clarifying_suggestions=_STANDARD_SUGGESTIONS if not result.ready else [],
        )


__all__ = ["QuestionReadinessNode"]
