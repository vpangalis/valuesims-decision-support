from __future__ import annotations

import logging

from langchain_openai import AzureChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from backend.workflow.models import QuestionReadinessNodeOutput, QuestionReadinessResult

_logger = logging.getLogger(__name__)


class QuestionReadinessNode:
    _SYSTEM_PROMPT = (
        "You are a readiness checker for an industrial incident decision-support assistant. "
        "Decide whether the user's question is specific enough to answer given the context. "
        "Return strict JSON only — no explanation, no markdown."
    )

    _USER_PROMPT_TEMPLATE = (
        "case_loaded: {case_loaded}\nintent: {intent}\nquestion: {question}\n\n"
        "OVERRIDE RULE: If case_loaded is true, you MUST return ready: true for any "
        "OPERATIONAL_CASE, SIMILARITY_SEARCH, STRATEGY_ANALYSIS, or KPI_ANALYSIS intent. "
        "A loaded case means the user is actively working on that case. "
        "Never return ready: false citing a missing case when case_loaded is true. "
        "This rule takes absolute precedence over all other reasoning.\n\n"
        "PORTFOLIO OVERRIDE: If intent is KPI_ANALYSIS or STRATEGY_ANALYSIS, you MUST return "
        "ready: true regardless of whether case_loaded is true or false. Portfolio-level questions "
        "about counts, trends, patterns, and systemic issues never require a loaded case. "
        "This rule takes absolute precedence over all other reasoning.\n\n"
        "Return ONLY this JSON:\n"
        '{{"ready": true, "clarifying_question": ""}} or\n'
        '{{"ready": false, "clarifying_question": "<one plain sentence asking for clarification>"}}\n\n'
        "Rules:\n"
        "- Portfolio-level questions about overall performance, trends, recurring problems, "
        "organisational patterns, metrics, and KPIs are always answerable without a loaded case — "
        "return ready=true regardless of whether a case is loaded.\n"
        "- Questions asking whether a similar problem has occurred before, whether the organisation "
        "has seen this type of failure, or whether there are precedents for a specific component or "
        "failure type — are always ready regardless of case status; the question itself provides "
        "sufficient context for a similarity search — return ready=true.\n"
        "- Only questions explicitly about a specific ongoing investigation — asking what to do next, "
        "what gaps exist, what the root cause is, or what actions to take — require a loaded case.\n"
        "- If the question is clear and answerable with the available context, return ready=true.\n"
        "- If a case is not loaded and the question requires specific case data, return ready=false.\n"
        "- If the question is too vague to answer, return ready=false.\n"
        "- If the question involves investigating, analysing, or reviewing the progress or status of work — "
        "such as identifying gaps, determining next steps, finding root causes, or deciding what to focus on — "
        "and no case is loaded, the clarifying_question must always invite the user to load a case first, "
        "not ask them to rephrase or provide more detail.\n"
        "- The clarifying_question must be written in plain, friendly language only."
    )

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
