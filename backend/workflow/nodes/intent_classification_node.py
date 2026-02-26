from __future__ import annotations

from backend.infra.llm_logging_client import LoggedLanguageModelClient
from backend.workflow.models import IntentClassificationResult, IntentNodeOutput


class IntentClassificationNode:
    _VALID_INTENTS = {
        "OPERATIONAL_CASE",
        "SIMILARITY_SEARCH",
        "STRATEGY_ANALYSIS",
        "KPI_ANALYSIS",
    }

    # Promote module-level prompt to class attribute.
    _SYSTEM_PROMPT = (
        "You are the routing classifier for an industrial incident decision-support system. "
        "Your only job is to read the user's question plus context and return a single routing intent. "
        "Return strict JSON only \u2014 no explanation, no markdown."
    )

    def __init__(self, llm_client: LoggedLanguageModelClient) -> None:
        self._llm_client = llm_client

    def run(
        self,
        question: str,
        case_id: str | None,
        previous_question: str | None = None,
    ) -> IntentNodeOutput:
        clean_question = (question or "").strip()
        if not clean_question:
            raise ValueError("question is required")

        case_loaded = bool(case_id and str(case_id).strip())
        prev_q_line = (
            f"previous_question: {previous_question.strip()}\n"
            if previous_question and previous_question.strip()
            else "previous_question: (none)\n"
        )

        user_prompt = (
            "Classify this request and return ONLY this JSON:\n"
            "{\n"
            '  "intent": "OPERATIONAL_CASE|SIMILARITY_SEARCH|STRATEGY_ANALYSIS|KPI_ANALYSIS",\n'
            '  "scope": "LOCAL|COUNTRY|GLOBAL",\n'
            '  "confidence": 0.0\n'
            "}\n\n"
            "=== NODE DEFINITIONS ===\n\n"
            "OPERATIONAL_CASE — use when:\n"
            "  • A case IS loaded AND the question is about next steps, current status, gaps,\n"
            "    what to do now, or how complete the investigation is.\n"
            "  Examples: 'What should we focus on next?', 'Are there gaps in our containment\n"
            "    actions?', 'What does the team need for root cause analysis?',\n"
            "    'How complete is our problem definition?',\n"
            "    'What is missing from our investigation so far?'\n\n"
            "SIMILARITY_SEARCH — use when:\n"
            "  • The question asks to find, compare, or reference other past or closed cases.\n"
            "  • A case may or may not be loaded.\n"
            "  Examples: 'Have we seen this type of failure before?',\n"
            "    'Find similar incidents involving bearing failures',\n"
            "    'Are there cases with the same root cause?',\n"
            "    'What do closed cases tell us about this problem?'\n\n"
            "STRATEGY_ANALYSIS — use when:\n"
            "  • The question is portfolio-level: patterns, trends, systemic issues,\n"
            "    organisational weaknesses, fleet-wide recurring failures, supplier problems,\n"
            "    or a big-picture view of the entire case history.\n"
            "  • No single case is the focus — the whole case portfolio is the subject.\n"
            "  Examples: 'What are our most recurring failure categories?',\n"
            "    'Are there systemic weaknesses across the fleet?',\n"
            "    'Which suppliers cause the most problems?',\n"
            "    'What does our case history reveal about organisational gaps?',\n"
            "    'Give me a strategic overview of our incident portfolio',\n"
            "    'Are there recurring issues across multiple cases?'\n\n"
            "KPI_ANALYSIS — use when:\n"
            "  • The question is about metrics, counts, frequencies, timelines, or performance\n"
            "    indicators derived from the case database.\n"
            "  Examples: 'How many cases have we opened this year?',\n"
            "    'What is our average resolution time?',\n"
            "    'How many cases are currently open?',\n"
            "    'What percentage of cases are closed?',\n"
            "    'Show me the trend in incident frequency'\n\n"
            "=== TIEBREAKER RULES (apply in order) ===\n"
            "1. If question explicitly mentions a specific case ID → OPERATIONAL_CASE.\n"
            "2. If no case is loaded AND question could be operational → STRATEGY_ANALYSIS.\n"
            "3. If previous_question was STRATEGY_ANALYSIS and new question is a follow-up → STRATEGY_ANALYSIS.\n"
            "4. When truly ambiguous → OPERATIONAL_CASE.\n\n"
            "=== SCOPE RULES ===\n"
            "• LOCAL when local/site-level language appears.\n"
            "• COUNTRY when country-level language appears.\n"
            "• GLOBAL for cross-country or no geographic qualifier.\n\n"
            "=== INPUT ===\n"
            f"case_loaded: {'true' if case_loaded else 'false'}\n"
            f"{prev_q_line}"
            f"question: {clean_question}"
        )

        classification = self._llm_client.complete_json(
            system_prompt=IntentClassificationNode._SYSTEM_PROMPT,
            user_prompt=user_prompt,
            response_model=IntentClassificationResult,
            temperature=0.0,
            user_question=clean_question,
        )

        # Validation: if LLM returns an unrecognised intent, default to OPERATIONAL_CASE
        if classification.intent not in IntentClassificationNode._VALID_INTENTS:
            classification = IntentClassificationResult(
                intent="OPERATIONAL_CASE",  # type: ignore[arg-type]
                scope=classification.scope,
                confidence=0.5,
            )

        return IntentNodeOutput(classification=classification)


__all__ = ["IntentClassificationNode"]
