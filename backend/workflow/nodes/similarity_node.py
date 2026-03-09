from __future__ import annotations

import json
from typing import Any

from backend.state import IncidentGraphState
from backend.config import Settings
from backend.llm import get_llm
from langchain_openai import AzureChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from backend.tools import search_similar_cases, search_knowledge_base
from backend.workflow.nodes.node_parsing_utils import (
    extract_similarity_suggestions,
    format_d_states,
)
from backend.workflow.services.knowledge_formatter import build_refs_block
from backend.prompts import SIMILARITY_SYSTEM_PROMPT


def similarity_node(state: IncidentGraphState) -> dict:
    """Find similar historical cases and extract patterns."""
    question = state.get("question", "")
    case_id = state.get("case_id")
    case_context = state.get("case_context")
    case_status = state.get("case_status")

    llm = get_llm("reasoning", 0.2)

    cases = search_similar_cases.invoke(
        {"query": question, "current_case_id": case_id, "country": _resolve_country(state)}
    )
    knowledge_docs = search_knowledge_base.invoke(
        {"query": question, "top_k": 4, "cosolve_phase": "root_cause"}
    )

    # Build case context summary
    if case_context:
        case_context_summary = format_d_states(case_context)
    else:
        case_context_summary = (
            "No active case loaded \u2014 reasoning from question description only."
        )

    # Format retrieved cases
    supporting_cases_dicts = [_to_dict(item) for item in cases]
    if supporting_cases_dicts:
        formatted_cases = json.dumps(supporting_cases_dicts, indent=2, default=str)
    else:
        formatted_cases = "No cases retrieved from the knowledge base."

    if knowledge_docs:
        knowledge_block = "\n".join(
            f"Per {(getattr(item, 'source', None) or getattr(item, 'doc_id', ''))}"
            f"{(' [' + getattr(item, 'section_title', '') + ']') if getattr(item, 'section_title', None) else ''}: "
            f"{(getattr(item, 'content_text', '') or '')[:600]}"
            for item in knowledge_docs
        )
    else:
        knowledge_block = "No relevant knowledge documents found for this case."

    status_value = (case_status or "open").lower()
    user_prompt = (
        f"USER QUESTION: {question}\n"
        f"ACTIVE CASE STATUS: {status_value}\n\n"
        "--- ACTIVE CASE CONTEXT ---\n"
        f"{case_context_summary}\n\n"
        "--- RETRIEVED CLOSED CASES ---\n"
        f"{formatted_cases}\n\n"
        "--- KNOWLEDGE BASE REFERENCES ---\n"
        f"{knowledge_block}"
    )

    response_text = llm.invoke([
        SystemMessage(content=SIMILARITY_SYSTEM_PROMPT),
        HumanMessage(content=user_prompt),
    ]).content
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

    suggestions = extract_similarity_suggestions(response_text)

    return {
        "similarity_draft": {
            "summary": response_text,
            "supporting_cases": [_to_dict(c) for c in cases],
            "suggestions": suggestions,
        },
        "_last_node": "similarity_node",
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


