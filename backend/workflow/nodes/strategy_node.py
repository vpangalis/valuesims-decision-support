from __future__ import annotations

import json
import logging
from typing import Any

from backend.state import IncidentGraphState
from backend.config import Settings
from backend.llm import get_llm
from langchain_openai import AzureChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from backend.tools import search_cases_for_pattern_analysis, search_knowledge_base
from backend.workflow.services.knowledge_formatter import build_refs_block
from backend.prompts import (
    STRATEGY_SYSTEM_PROMPT,
    STRATEGY_ESCALATION_SYSTEM_PROMPT,
)

_logger = logging.getLogger("strategy_node")

_ANCHOR_QUERIES: list[str] = [
    "recurring failures maintenance",
    "component failure root cause",
]
_ANCHOR_QUERY_MIN_CASES: int = 5


def strategy_node(state: IncidentGraphState) -> dict:
    """Run portfolio-level strategy reasoning."""
    return _run_strategy(state, model_name=None)


def _run_strategy(state: IncidentGraphState, model_name: str | None = None) -> dict:
    """Core strategy logic shared by strategy_node and strategy_escalation_node."""
    question = state.get("question", "")
    country = _resolve_country(state)

    llm = get_llm(model_name or "reasoning", 0.2)

    # Read escalation state
    strategy_escalated = bool(state.get("strategy_escalated"))
    strategy_fail_section = str(state.get("strategy_fail_section") or "")
    strategy_fail_reason = str(state.get("strategy_fail_reason") or "")
    strategy_response = str(state.get("strategy_response") or "")

    # --- Pass 1 (semantic): user's question against case index
    semantic_cases = search_cases_for_pattern_analysis.invoke(
        {"query": question, "country": country, "top_k": 4}
    )
    _logger.info("[strategy_node] semantic retrieval \u2192 %d results", len(semantic_cases))

    # --- Pass 2 (broad): anchor queries
    anchor_cases: list = []
    if len(semantic_cases) >= _ANCHOR_QUERY_MIN_CASES:
        for anchor_q in _ANCHOR_QUERIES:
            results = search_cases_for_pattern_analysis.invoke(
                {"query": anchor_q, "country": country, "top_k": 5}
            )
            _logger.info("[strategy_node] broad retrieval '%s' \u2192 %d results", anchor_q, len(results))
            anchor_cases.extend(results)

    knowledge_docs = search_knowledge_base.invoke(
        {"query": question, "top_k": 4, "cosolve_phase": "prevent"}
    )
    _logger.info("[strategy_node] knowledge retrieval \u2192 %d results", len(knowledge_docs))

    # Deduplicate cases by case_id
    seen_ids: set[str] = set()
    all_cases: list = []
    for case in anchor_cases + list(semantic_cases):
        cid = getattr(case, "case_id", None) or (case.get("case_id") if isinstance(case, dict) else None)
        if cid and cid not in seen_ids:
            seen_ids.add(cid)
            all_cases.append(case)
    _logger.info("[strategy_node] unique cases after dedup: %d", len(all_cases))

    # Cap knowledge docs at 4
    knowledge_docs = list(knowledge_docs)[:4]

    formatted_cases = json.dumps(
        [_to_dict(c) for c in all_cases], indent=2, default=str,
    )
    formatted_knowledge = "\n".join(
        f"Per {(getattr(item, 'source', None) or getattr(item, 'doc_id', ''))}"
        f"{(' [' + getattr(item, 'section_title', '') + ']') if getattr(item, 'section_title', None) else ''}: "
        f"{(getattr(item, 'content_text', '') or '')[:600]}"
        for item in knowledge_docs
    )

    # If escalated and a specific section failed, use targeted regeneration prompt
    if strategy_escalated and strategy_fail_section and strategy_response:
        system_prompt = STRATEGY_ESCALATION_SYSTEM_PROMPT.format(
            fail_section=strategy_fail_section,
            fail_reason=strategy_fail_reason,
            original_response=strategy_response,
            formatted_cases=formatted_cases,
        )
        user_prompt = f"USER QUESTION: {question}"
    else:
        system_prompt = STRATEGY_SYSTEM_PROMPT
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
    response_text = _ensure_general_advice_prefix(response_text)
    if knowledge_docs:
        refs = build_refs_block(knowledge_docs)
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

    suggestions = _extract_suggestions(response_text)

    return {
        "strategy_draft": {
            "summary": response_text,
            "supporting_cases": [_to_dict(c) for c in all_cases],
            "supporting_knowledge": [_to_dict(k) for k in knowledge_docs],
            "suggestions": suggestions,
        },
        "_last_node": "strategy_node",
    }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _to_dict(obj: Any) -> dict:
    """Convert a Pydantic model or dict to a plain dict."""
    if isinstance(obj, dict):
        return obj
    try:
        return dict(obj)
    except Exception:
        return vars(obj)


def _resolve_country(state: IncidentGraphState) -> str | None:
    """Extract country from case context if available."""
    case_context = state.get("case_context") or {}
    if isinstance(case_context, dict):
        direct = case_context.get("organization_country")
        if isinstance(direct, str) and direct.strip():
            return direct.strip()
    return None


def _ensure_general_advice_prefix(text: str) -> str:
    """Insert \u26a0 prefix into [GENERAL ADVICE] content if the LLM omitted it."""
    marker = "[GENERAL ADVICE]"
    if marker not in text:
        return text
    parts = text.split(marker, 1)
    after = parts[1].lstrip("\n").lstrip()
    if not after.startswith("\u26a0"):
        parts[1] = "\n\u26a0\ufe0f " + after
    return marker.join(parts)


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
                    suggestions.append({
                        "label": (q[:40] + "..." if len(q) > 40 else q),
                        "question": q, "type": "team",
                    })
            elif line.upper().startswith("COSOLVE:"):
                q = line[8:].strip().strip('"')
                if q:
                    suggestions.append({
                        "label": (q[:40] + "..." if len(q) > 40 else q),
                        "question": q, "type": "cosolve",
                    })
    except Exception:
        pass
    return suggestions


