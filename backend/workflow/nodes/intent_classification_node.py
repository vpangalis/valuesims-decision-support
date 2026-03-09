from __future__ import annotations

from langchain_openai import AzureChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from backend.state import IncidentGraphState
from backend.llm import get_llm
from backend.workflow.nodes.intent_coercion import _RawClassification, coerce_raw
from backend.prompts import INTENT_CLASSIFICATION_SYSTEM_PROMPT


def intent_classification_node(state: IncidentGraphState) -> dict:
    """Classify the user's question into an intent and scope."""
    question = (state.get("question") or "").strip()
    if not question:
        raise ValueError("question is required")

    case_id = state.get("case_id")
    case_loaded = bool(case_id and str(case_id).strip())
    prev_q_line = "previous_question: (none)\n"

    user_prompt = (
        "Classify this request and return ONLY this JSON:\n"
        "{\n"
        '  "intent": "OPERATIONAL_CASE|SIMILARITY_SEARCH|STRATEGY_ANALYSIS|KPI_ANALYSIS",\n'
        '  "scope": "LOCAL|COUNTRY|GLOBAL",\n'
        '  "confidence": 0.0\n'
        "}\n\n"
        "=== NODE DEFINITIONS ===\n\n"
        "OPERATIONAL_CASE \u2014 use when:\n"
        "  \u2022 A case IS loaded AND the question is about next steps, current status, gaps,\n"
        "    what to do now, or how complete the investigation is.\n"
        "  \u2022 A case IS loaded AND the question asks what a procedure, standard,\n"
        "    regulation, or obligation requires or specifies.\n"
        "  EXCLUSION: Do NOT classify as OPERATIONAL_CASE if the question is about the\n"
        "    portfolio as a whole.\n\n"
        "SIMILARITY_SEARCH \u2014 use when:\n"
        "  \u2022 The question asks to find, compare, or reference other past or closed cases.\n\n"
        "STRATEGY_ANALYSIS \u2014 use when:\n"
        "  \u2022 The question is portfolio-level: patterns, trends, systemic issues.\n"
        "  \u2022 The question asks to LIST or IDENTIFY specific cases by status, location, country.\n\n"
        "KPI_ANALYSIS \u2014 use when:\n"
        "  \u2022 The question is about aggregate metrics, counts, frequencies, timelines.\n\n"
        "=== TIEBREAKER RULES (apply in order) ===\n"
        "0. If a case IS loaded AND the question asks what a procedure requires \u2192 OPERATIONAL_CASE.\n"
        "1. If question explicitly mentions a specific case ID \u2192 OPERATIONAL_CASE.\n"
        "2. If no case is loaded AND question could be operational \u2192 STRATEGY_ANALYSIS.\n"
        "3. If previous_question was STRATEGY_ANALYSIS and new question is a follow-up \u2192 STRATEGY_ANALYSIS.\n"
        "4. Counts/rates/trends \u2192 KPI_ANALYSIS. Listing/identifying cases \u2192 STRATEGY_ANALYSIS.\n"
        "5. When truly ambiguous \u2192 OPERATIONAL_CASE.\n\n"
        "=== SCOPE RULES ===\n"
        "\u2022 LOCAL when local/site-level language appears.\n"
        "\u2022 COUNTRY when country-level language appears.\n"
        "\u2022 GLOBAL for cross-country or no geographic qualifier.\n\n"
        "=== INPUT ===\n"
        f"case_loaded: {'true' if case_loaded else 'false'}\n"
        f"{prev_q_line}"
        f"question: {question}"
    )

    llm = get_llm("intent", 0.0)
    raw = llm.with_structured_output(_RawClassification).invoke([
        SystemMessage(content=INTENT_CLASSIFICATION_SYSTEM_PROMPT),
        HumanMessage(content=user_prompt),
    ])
    result = coerce_raw(raw)

    return {
        "classification": {
            "intent": result.intent,
            "scope": result.scope,
            "confidence": result.confidence,
        },
        "_last_node": "intent_classification_node",
    }


