from __future__ import annotations

import json
import logging
from typing import Any

from backend.config import Settings
from backend.infra.llm_logging_client import LoggedLanguageModelClient
from backend.retrieval.hybrid_retriever import HybridRetriever
from backend.workflow.models import StrategyDraftPayload, StrategyNodeOutput

_logger = logging.getLogger("strategy_node")


class StrategyNode:
    _STRATEGY_SYSTEM_PROMPT = """\
You are a senior quality strategy advisor with access to the full portfolio of incident cases.
Your role is to reason across the entire case history and answer the user's strategic question.

Before answering, you MUST reason internally through these steps — do not include this
reasoning in your output:

STEP 1 — PORTFOLIO SCAN
Read all retrieved cases. For each, note: case ID, status (open or closed), failure category,
and root cause if available. Do not skip any case.

STEP 2 — PATTERN DETECTION
Group cases by failure category. Flag any category with 2+ cases as a trend.
Flag any category with 3+ cases as systemic.

STEP 3 — WEAKNESS INFERENCE
For each identified pattern, name the organisational gap that allowed it to recur.
Be specific about what process, oversight, or capability is missing.

Now answer the question using EXACTLY these five sections in EXACTLY this order.
No other sections are permitted.

[SYSTEMIC PATTERNS IDENTIFIED]
Name each pattern explicitly. For each pattern, cite the supporting case IDs.
Flag any open case as [EMERGING — case_id]. Be specific: name the component or process,
not a generic category. If fewer than 2 cases support a pattern, do not call it systemic.

[ROOT CAUSE CATEGORIES]
Group all cases into named root cause categories (not D-step codes — use plain names).
For each category, list the case IDs that fall into it.
If a case's root cause is unknown or not documented, say so explicitly.

[ORGANISATIONAL WEAKNESSES]
Identify the process, oversight or capability gaps revealed by the patterns.
When 2+ cases support a weakness, state it with confidence — do not hedge.
If there is only one case for a weakness, note that more data is needed to confirm.
Every weakness must cite at least one named case ID.
Do not list generic weaknesses not supported by the retrieved cases.

[GENERAL ADVICE]
\u26a0\ufe0f General portfolio-level guidance not specific to this data:
Provide 3-5 recommendations at the portfolio or fleet level.
These should be generic quality management / continuous improvement recommendations.
Do not give single-incident advice here.

[WHAT TO EXPLORE NEXT]
Provide exactly 6 items: 3 prefixed with TEAM: and 3 prefixed with COSOLVE:
TEAM items are questions for the management team to discuss internally.
COSOLVE items are specific questions to ask the CoSolve system.
All 6 questions must be at portfolio, fleet, or organisational scope — not incident-level.
Format each item on its own line exactly like this:
TEAM: <question>
TEAM: <question>
TEAM: <question>
COSOLVE: <question>
COSOLVE: <question>
COSOLVE: <question>

CRITICAL RULES:
- 300-400 words total across all five sections.
- Every pattern and weakness must cite at least one named case ID.
- Open cases must be flagged as EMERGING with their case ID.
- No D-step codes (D1/D2 etc.) in output — use plain language labels only.
- Do not hallucinate cases not present in the retrieved context.
- If fewer than 2 cases were retrieved, state the data limitation clearly in
  [SYSTEMIC PATTERNS IDENTIFIED] and reason conservatively throughout.
- [WHAT TO EXPLORE NEXT] items must be portfolio/fleet/org level, not incident level.
- SECTION ORDER IS MANDATORY. No sections may be omitted or reordered.
- The [GENERAL ADVICE] section MUST start with the exact characters ⚠️ (warning emoji)
  immediately after the section marker — this signals to the reader that the advice is
  generic and not grounded in the retrieved case data.
- Return plain text only. No JSON. No markdown beyond the section labels.
- [WHAT TO EXPLORE NEXT] must be the final section. Nothing may appear after it.\
"""
    _ESCALATION_SYSTEM_PROMPT = """\
A previous draft strategy response was rejected by the quality auditor.

The failing section was: {fail_section}
The reason for failure was: {fail_reason}

Rewrite ONLY the failing section, keeping all other sections unchanged.
Return the COMPLETE response with all five sections in mandatory order:
[SYSTEMIC PATTERNS IDENTIFIED], [ROOT CAUSE CATEGORIES], [ORGANISATIONAL WEAKNESSES],
[GENERAL ADVICE], [WHAT TO EXPLORE NEXT]

Requirements for [WHAT TO EXPLORE NEXT] if that is the failing section:
- Exactly 6 items: 3 lines starting with TEAM: and 3 lines starting with COSOLVE:
- All items at portfolio/fleet/org scope, not incident-level
- Each on its own line

Original response:
{original_response}

Retrieved cases for context:
{formatted_cases}\
"""

    def __init__(
        self,
        hybrid_retriever: HybridRetriever,
        llm_client: LoggedLanguageModelClient,
        settings: Settings,
    ) -> None:
        self._hybrid_retriever = hybrid_retriever
        self._llm_client = llm_client
        self._settings = settings

    def run(self, question: str, country: str | None) -> StrategyNodeOutput:
        return self.run_with_model_override(
            question=question,
            country=country,
            model_name=None,
        )

    def run_with_model_override(
        self,
        question: str,
        country: str | None,
        model_name: str | None,
        state: dict[str, Any] | None = None,
    ) -> StrategyNodeOutput:
        # Escalation path: rewrite only the failing section using premium model
        if state:
            strategy_escalated = bool(state.get("strategy_escalated"))
            strategy_fail_section = str(state.get("strategy_fail_section") or "")
            strategy_fail_reason = str(state.get("strategy_fail_reason") or "")
            strategy_response = str(state.get("strategy_response") or "")
        else:
            strategy_escalated = False
            strategy_fail_section = ""
            strategy_fail_reason = ""
            strategy_response = ""

        # --- Pass 1 (broad): two fixed anchor queries against case index
        _ANCHOR_QUERIES = [
            "recurring failures maintenance",
            "component failure root cause",
        ]
        anchor_cases: list = []
        case_index = self._settings.CASE_INDEX_NAME
        knowledge_index = self._settings.KNOWLEDGE_INDEX_NAME
        for anchor_q in _ANCHOR_QUERIES:
            results = self._hybrid_retriever.retrieve_cases_for_pattern_analysis(
                query=anchor_q,
                country=country,
                top_k=5,
            )
            _logger.info(
                "[strategy_node] broad retrieval '%s' → %d results from %s",
                anchor_q,
                len(results),
                case_index,
            )
            anchor_cases.extend(results)
        _logger.info("[STRATEGY_DEBUG] broad_cases count: %d", len(anchor_cases))

        # --- Pass 2 (semantic): user's question against case index + knowledge index
        semantic_cases = self._hybrid_retriever.retrieve_cases_for_pattern_analysis(
            query=question,
            country=country,
            top_k=4,
        )
        _logger.info(
            "[strategy_node] semantic retrieval '%s' → %d results from %s",
            question,
            len(semantic_cases),
            case_index,
        )
        _logger.info("[STRATEGY_DEBUG] semantic_cases count: %d", len(semantic_cases))
        knowledge_docs = self._hybrid_retriever.retrieve_knowledge(
            query=question,
            top_k=4,
        )
        _logger.info(
            "[strategy_node] knowledge retrieval '%s' → %d results from %s",
            question,
            len(knowledge_docs),
            knowledge_index,
        )
        _logger.info("[STRATEGY_DEBUG] knowledge_docs count: %d", len(knowledge_docs))

        # Deduplicate cases by case_id
        seen_ids: set[str] = set()
        all_cases: list = []
        for case in anchor_cases + semantic_cases:
            if case.case_id not in seen_ids:
                seen_ids.add(case.case_id)
                all_cases.append(case)
        _logger.info("[STRATEGY_DEBUG] unique cases after dedup: %d", len(all_cases))
        for c in all_cases:
            _logger.info("[STRATEGY_DEBUG] case: %s", getattr(c, "case_id", str(c)))

        # Cap knowledge docs at 4
        knowledge_docs = knowledge_docs[:4]

        formatted_cases = json.dumps(
            [c.model_dump(mode="json") for c in all_cases],
            indent=2,
            default=str,
        )
        formatted_knowledge = json.dumps(
            [k.model_dump(mode="json") for k in knowledge_docs],
            indent=2,
            default=str,
        )
        _logger.info(
            "[STRATEGY_DEBUG] case_context length: %d chars", len(formatted_cases)
        )
        _logger.info("[STRATEGY_DEBUG] case_context preview: %s", formatted_cases[:300])

        # If escalated and a specific section failed, use targeted regeneration prompt
        if strategy_escalated and strategy_fail_section and strategy_response:
            system_prompt = StrategyNode._ESCALATION_SYSTEM_PROMPT.format(
                fail_section=strategy_fail_section,
                fail_reason=strategy_fail_reason,
                original_response=strategy_response,
                formatted_cases=formatted_cases,
            )
            user_prompt = f"USER QUESTION: {question}"
        else:
            system_prompt = StrategyNode._STRATEGY_SYSTEM_PROMPT
            user_prompt = (
                f"USER QUESTION: {question}\n\n"
                "--- RETRIEVED CASES ---\n"
                f"{formatted_cases}\n\n"
                "--- KNOWLEDGE DOCUMENTS ---\n"
                f"{formatted_knowledge}"
            )

        response_text = self._llm_client.complete_text(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.2,
            user_question=question,
            model_name=model_name,
        )
        _logger.info(
            "[STRATEGY_DEBUG] LLM response length: %d chars", len(response_text)
        )
        _logger.info("[STRATEGY_DEBUG] LLM response preview: %s", response_text[:300])

        suggestions = self._extract_suggestions(response_text)

        return StrategyNodeOutput(
            strategy_draft=StrategyDraftPayload(
                summary=response_text,
                supporting_cases=all_cases,
                supporting_knowledge=knowledge_docs,
                suggestions=suggestions,
            )
        )

    @staticmethod
    def _extract_suggestions(response_text: str) -> list[dict]:
        """Extract [WHAT TO EXPLORE NEXT] TEAM:/COSOLVE: items as structured chips."""
        suggestions: list[dict] = []
        try:
            marker = "[WHAT TO EXPLORE NEXT]"
            if marker not in response_text:
                return []
            section = response_text.split(marker, 1)[1].strip()

            for line in section.split("\n"):
                line = line.strip()
                if line.upper().startswith("TEAM:"):
                    q = line[5:].strip().strip('"')
                    if q:
                        suggestions.append(
                            {
                                "label": (q[:40] + "..." if len(q) > 40 else q),
                                "question": q,
                                "type": "team",
                            }
                        )
                elif line.upper().startswith("COSOLVE:"):
                    q = line[8:].strip().strip('"')
                    if q:
                        suggestions.append(
                            {
                                "label": (q[:40] + "..." if len(q) > 40 else q),
                                "question": q,
                                "type": "cosolve",
                            }
                        )
        except Exception:
            pass
        return suggestions


__all__ = ["StrategyNode"]
