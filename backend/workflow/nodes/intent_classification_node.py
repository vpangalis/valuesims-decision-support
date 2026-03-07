from __future__ import annotations

from langchain_openai import AzureChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from backend.workflow.models import IntentNodeOutput
from backend.workflow.nodes.intent_coercion import _RawClassification, coerce_raw


class IntentClassificationNode:
    # Promote module-level prompt to class attribute.
    _SYSTEM_PROMPT = (
        "You are the routing classifier for an industrial incident decision-support system. "
        "Your only job is to read the user's question plus context and return a single routing intent. "
        "Return strict JSON only \u2014 no explanation, no markdown."
    )

    def __init__(self, llm_client: AzureChatOpenAI) -> None:
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
            "  • A case IS loaded AND the question asks what a procedure, standard,\n"
            "    regulation, or obligation requires or specifies — e.g. 'what records\n"
            "    must be kept', 'what are the notification obligations', 'what does\n"
            "    the standard say', 'how often must X be done', 'what are the\n"
            "    requirements for Y'. These are knowledge-grounded questions best\n"
            "    answered in the context of the loaded case.\n"
            "  EXCLUSION: Do NOT classify as OPERATIONAL_CASE if the question is about the\n"
            "    portfolio as a whole — asking how many cases exist, which cases are open or\n"
            "    closed, listing cases by status or country, or any question that could be\n"
            "    answered without reference to the currently loaded case. These are\n"
            "    KPI_ANALYSIS or STRATEGY_ANALYSIS questions regardless of whether a case\n"
            "    is loaded.\n"
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
            "  • The question asks to LIST or IDENTIFY specific cases by status, location,\n"
            "    country, or any other filter — even if phrased as 'show me' or 'give me'.\n"
            "    NOTE: listing/identifying cases routes here, NOT to KPI_ANALYSIS.\n"
            "    KPI_ANALYSIS handles counts and aggregate metrics; STRATEGY_ANALYSIS\n"
            "    handles case identification and enumeration.\n"
            "  EXCLUSION: Do NOT classify as STRATEGY_ANALYSIS if a case IS loaded\n"
            "  AND the question asks what a procedure, standard, or obligation requires\n"
            "  (even if it mentions suppliers or organisational topics). Route to\n"
            "  OPERATIONAL_CASE instead.\n"
            "  Examples: 'What are our most recurring failure categories?',\n"
            "    'Are there systemic weaknesses across the fleet?',\n"
            "    'Which suppliers cause the most problems?',\n"
            "    'What does our case history reveal about organisational gaps?',\n"
            "    'Give me a strategic overview of our incident portfolio',\n"
            "    'Are there recurring issues across multiple cases?',\n"
            "    'Which areas have the most recurring problems?',\n"
            "    'Which areas need organisational attention?',\n"
            "    'Show me all open cases in Belgium',\n"
            "    'List open cases by country',\n"
            "    'Which cases are currently open in Greece?',\n"
            "    'Give me the open case IDs for France'\n\n"
            "KPI_ANALYSIS — use when:\n"
            "  • The question is about aggregate metrics, counts, frequencies, timelines, or\n"
            "    performance indicators — answers expressible as a number, rate, or chart.\n"
            "  • The question asks HOW MANY, WHAT PERCENTAGE, WHAT IS THE RATE/AVERAGE/TREND —\n"
            "    not which specific cases or IDs.\n"
            "  Examples: 'How many cases have we opened this year?',\n"
            "    'What is our average resolution time?',\n"
            "    'How many cases are currently open?',\n"
            "    'What percentage of cases are closed?',\n"
            "    'Show me the trend in incident frequency',\n"
            "    'How is our overall performance this year?'\n\n"
            "=== TIEBREAKER RULES (apply in order) ===\n"
            "0. If a case IS loaded AND the question asks what a procedure, standard,\n"
            "   regulation, or obligation requires or specifies → OPERATIONAL_CASE.\n"
            "   This takes priority over all other tiebreakers.\n"
            "1. If question explicitly mentions a specific case ID → OPERATIONAL_CASE.\n"
            "2. If no case is loaded AND question could be operational → STRATEGY_ANALYSIS.\n"
            "3. If previous_question was STRATEGY_ANALYSIS and new question is a follow-up → STRATEGY_ANALYSIS.\n"
            "4. TIEBREAKER — KPI_ANALYSIS vs STRATEGY_ANALYSIS: If the question asks for\n"
            "   aggregate numbers, counts, rates, durations, frequencies, or trends that\n"
            "   could be expressed as a chart or metric, prefer KPI_ANALYSIS. If the\n"
            "   question asks to LIST, IDENTIFY, or ENUMERATE specific cases (by status,\n"
            "   country, location, or any filter), prefer STRATEGY_ANALYSIS — even if the\n"
            "   word 'open' or a country name appears. Only use STRATEGY_ANALYSIS when the\n"
            "   question seeks narrative insight, case identification, patterns, or\n"
            "   organisational conclusions that cannot be answered with a single number.\n"
            "5. When truly ambiguous → OPERATIONAL_CASE.\n\n"
            "=== SCOPE RULES ===\n"
            "• LOCAL when local/site-level language appears.\n"
            "• COUNTRY when country-level language appears.\n"
            "• GLOBAL for cross-country or no geographic qualifier.\n"
            "  Example: 'by country', 'across countries', or 'grouped by country' without a named country → GLOBAL scope.\n\n"
            "=== INPUT ===\n"
            f"case_loaded: {'true' if case_loaded else 'false'}\n"
            f"{prev_q_line}"
            f"question: {clean_question}"
        )

        raw = self._llm_client.with_structured_output(_RawClassification).invoke([
            SystemMessage(content=IntentClassificationNode._SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ])
        classification = coerce_raw(raw)

        return IntentNodeOutput(classification=classification)


__all__ = ["IntentClassificationNode"]
