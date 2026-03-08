from __future__ import annotations

import json
import logging
from typing import Any

from backend.config import Settings
from backend.llm import get_llm
from langchain_openai import AzureChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from backend.retrieval.hybrid_retriever import HybridRetriever
from backend.workflow.models import StrategyPayload, StrategyNodeOutput
from backend.workflow.services.knowledge_formatter import knowledge_formatter
from backend.prompts import (
    STRATEGY_SYSTEM_PROMPT,
    STRATEGY_ESCALATION_SYSTEM_PROMPT,
)

_logger = logging.getLogger("strategy_node")


class StrategyNode:
    _STRATEGY_SYSTEM_PROMPT = STRATEGY_SYSTEM_PROMPT
    _ESCALATION_SYSTEM_PROMPT = STRATEGY_ESCALATION_SYSTEM_PROMPT

    _ANCHOR_QUERIES: list[str] = [
        "recurring failures maintenance",
        "component failure root cause",
    ]
    _ANCHOR_QUERY_MIN_CASES: int = 5

    def __init__(
        self,
        hybrid_retriever: HybridRetriever,
        llm_client: AzureChatOpenAI,
        settings: Settings,
    ) -> None:
        self._hybrid_retriever = hybrid_retriever
        self._llm_client = llm_client
        self._settings = settings

    def _resolve_llm(self, model_name: str | None) -> AzureChatOpenAI:
        """Return a deployment-specific LLM when model_name is given (escalation path)."""
        if model_name:
            return get_llm(deployment=model_name, temperature=self._llm_client.temperature)
        return self._llm_client

    def run(
        self,
        question: str,
        country: str | None,
        model_name: str | None = None,
        state: dict[str, Any] | None = None,
    ) -> StrategyNodeOutput:
        llm = self._resolve_llm(model_name)
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

        anchor_cases: list = []
        case_index = self._settings.CASE_INDEX_NAME
        knowledge_index = self._settings.KNOWLEDGE_INDEX_NAME

        # --- Pass 1 (semantic): user's question against case index
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

        # --- Pass 2 (broad): two fixed anchor queries against case index
        # Skip broad anchor pass when semantic results suggest a small
        # portfolio — anchor queries return the same cases as semantic
        # when fewer than _ANCHOR_QUERY_MIN_CASES cases exist.
        if len(semantic_cases) >= StrategyNode._ANCHOR_QUERY_MIN_CASES:
            for anchor_q in StrategyNode._ANCHOR_QUERIES:
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
        knowledge_docs = self._hybrid_retriever.retrieve_knowledge(
            query=question,
            top_k=4,
            cosolve_phase="prevent",
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
        formatted_knowledge = "\n".join(
            f"Per {(item.source or item.doc_id)}"
            f"{(' [' + item.section_title + ']') if item.section_title else ''}: "
            f"{(item.content_text or '')[:600]}"
            for item in knowledge_docs
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

        response_text = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]).content
        response_text = self._ensure_general_advice_prefix(response_text)
        if knowledge_docs:
            refs = knowledge_formatter.build_refs_block(knowledge_docs)
            knowledge_section = "\n\n[KNOWLEDGE REFERENCES]\n" + refs
            explore_marker = "[WHAT TO EXPLORE NEXT]"
            if explore_marker in response_text:
                idx = response_text.index(explore_marker)
                response_text = (
                    response_text[:idx].rstrip()
                    + knowledge_section
                    + "\n\n"
                    + response_text[idx:]
                )
            else:
                response_text = response_text + knowledge_section
        _logger.info(
            "[STRATEGY_DEBUG] LLM response length: %d chars", len(response_text)
        )
        _logger.info("[STRATEGY_DEBUG] LLM response preview: %s", response_text[:300])

        suggestions = self._extract_suggestions(response_text)

        return StrategyNodeOutput(
            strategy_draft=StrategyPayload(
                summary=response_text,
                supporting_cases=all_cases,
                supporting_knowledge=knowledge_docs,
                suggestions=suggestions,
            )
        )

    def _ensure_general_advice_prefix(self, text: str) -> str:
        """Insert ⚠️ prefix into [GENERAL ADVICE] content if the LLM omitted it.

        Prevents spurious strategy reflection failures caused by the LLM
        occasionally dropping the warning emoji despite prompt instructions.
        """
        marker = "[GENERAL ADVICE]"
        if marker not in text:
            return text
        parts = text.split(marker, 1)
        after = parts[1].lstrip("\n").lstrip()
        if not after.startswith("\u26a0"):
            parts[1] = "\n\u26a0\ufe0f " + after
        return marker.join(parts)

    def _extract_suggestions(self, response_text: str) -> list[dict]:
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
