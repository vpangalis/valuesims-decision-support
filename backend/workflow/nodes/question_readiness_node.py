from __future__ import annotations

import logging

from langchain_openai import AzureChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from backend.workflow.models import QuestionReadinessNodeOutput, QuestionReadinessResult
from backend.prompts import QUESTION_READINESS_SYSTEM_PROMPT, QUESTION_READINESS_USER_PROMPT_TEMPLATE

_logger = logging.getLogger(__name__)


class QuestionReadinessNode:
    _SYSTEM_PROMPT = QUESTION_READINESS_SYSTEM_PROMPT

    _USER_PROMPT_TEMPLATE = QUESTION_READINESS_USER_PROMPT_TEMPLATE

    _ALWAYS_READY_INTENTS: frozenset[str] = frozenset(
        {"KPI_ANALYSIS", "STRATEGY_ANALYSIS"}
    )

    def __init__(self, llm_client: AzureChatOpenAI) -> None:
        self._llm_client = llm_client

    def _deterministic_ready_check(
        self, intent: str, case_loaded: bool
    ) -> QuestionReadinessNodeOutput | None:
        """Return a ready=True output immediately for cases that are
        always ready by rule, without calling the LLM.

        Rule 1: any intent with a loaded case → always ready.
        Rule 2: KPI_ANALYSIS or STRATEGY_ANALYSIS → always ready
                regardless of case_loaded.

        Returns None when the deterministic rules do not apply —
        the caller must then proceed to the LLM check.
        """
        if case_loaded:
            return QuestionReadinessNodeOutput(
                question_ready=True, clarifying_question=""
            )
        if intent in QuestionReadinessNode._ALWAYS_READY_INTENTS:
            return QuestionReadinessNodeOutput(
                question_ready=True, clarifying_question=""
            )
        return None

    def run(
        self,
        question: str,
        intent: str,
        case_loaded: bool,
    ) -> QuestionReadinessNodeOutput:
        fast_result = self._deterministic_ready_check(intent, case_loaded)
        if fast_result is not None:
            return fast_result

        # LLM path: no case loaded + OPERATIONAL_CASE or
        # SIMILARITY_SEARCH — semantic check required.
        user_prompt = QuestionReadinessNode._USER_PROMPT_TEMPLATE.format(
            case_loaded="true" if case_loaded else "false",
            intent=intent,
            question=(question or "").strip(),
        )
        try:
            result = self._llm_client.with_structured_output(QuestionReadinessResult).invoke([
                SystemMessage(content=QuestionReadinessNode._SYSTEM_PROMPT),
                HumanMessage(content=user_prompt),
            ])
            return QuestionReadinessNodeOutput(
                question_ready=result.ready,
                clarifying_question=result.clarifying_question or "",
            )
        except Exception:  # noqa: BLE001
            _logger.warning(
                "QuestionReadinessNode: LLM call failed — defaulting to ready=True"
            )
            return QuestionReadinessNodeOutput(
                question_ready=True, clarifying_question=""
            )


__all__ = ["QuestionReadinessNode"]
