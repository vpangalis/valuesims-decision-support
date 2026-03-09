from __future__ import annotations

import json
from typing import Any

from backend.state import IncidentGraphState
from backend.config import Settings
from backend.llm import get_llm
from langchain_openai import AzureChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from backend.tools import (
    search_evidence,
    search_knowledge_base,
    search_similar_cases,
)
from backend.workflow.nodes.node_parsing_utils import (
    NEW_PROBLEM_KEYWORDS,
    extract_suggestions,
    format_d_states,
    is_new_problem_question,
    normalize_d_states,
)
from backend.workflow.services.knowledge_formatter import build_refs_block
from backend.prompts import (
    OPERATIONAL_NEW_PROBLEM_SYSTEM_PROMPT,
    OPERATIONAL_SYSTEM_PROMPT,
    OPERATIONAL_CLOSED_CASE_SYSTEM_PROMPT,
)


def operational_node(state: IncidentGraphState) -> dict:
    """Run operational reasoning for the currently loaded case."""
    return _run_operational(state, model_name=None)


def _run_operational(state: IncidentGraphState, model_name: str | None = None) -> dict:
    """Core operational logic shared by operational_node and operational_escalation_node."""
    question = state.get("question", "")
    case_id = state.get("case_id")
    case_context = state.get("case_context") or {}
    current_d_state = state.get("current_d_state")
    case_status = state.get("case_status")

    llm = get_llm(model_name or "reasoning", 0.2)
    op_phase = "root_cause" if case_status == "open" else "general"

    knowledge_docs = search_knowledge_base.invoke(
        {"query": question, "top_k": 4, "cosolve_phase": op_phase}
    )
    if knowledge_docs:
        knowledge_block = "\n".join(
            f"Per {(getattr(item, 'source', None) or getattr(item, 'doc_id', ''))}"
            f"{(' [' + getattr(item, 'section_title', '') + ']') if getattr(item, 'section_title', None) else ''}: "
            f"{(getattr(item, 'content_text', '') or '')[:600]}"
            for item in knowledge_docs
        )
    else:
        knowledge_block = "No relevant knowledge documents found for this case."

    # -- New-problem path (no case loaded) --
    if is_new_problem_question(question, case_id):
        user_prompt = f"USER QUESTION: {question}"
        user_prompt = (
            user_prompt + "\n--- KNOWLEDGE BASE REFERENCES ---\n" + knowledge_block
        )
        response_text = llm.invoke([
            SystemMessage(content=OPERATIONAL_NEW_PROBLEM_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ]).content
        if knowledge_docs:
            response_text = _inject_knowledge_refs(response_text, knowledge_docs)
        suggestions = extract_suggestions(response_text)
        return {
            "operational_draft": {
                "current_state": "No case loaded",
                "current_state_recommendations": response_text,
                "next_state_preview": "",
                "supporting_cases": [],
                "referenced_evidence": [],
                "suggestions": suggestions,
            },
            "_last_node": "operational_node",
        }

    # -- Closed-case path --
    if case_status == "closed" and case_id:
        supporting_cases = search_similar_cases.invoke(
            {"query": question, "current_case_id": case_id, "country": _extract_country(case_context)}
        )
        referenced_evidence = search_evidence.invoke({"case_id": case_id})
        user_prompt = (
            f"CLOSED CASE: {case_id}\n"
            f"USER QUESTION: {question}\n"
            "\n--- CASE HISTORY ---\n"
            f"{format_d_states(case_context)}\n"
            "\n--- SUPPORTING CLOSED CASES ---\n"
            f"{json.dumps([_to_dict(item) for item in supporting_cases], indent=2, default=str)}\n"
            "\n--- REFERENCED EVIDENCE ---\n"
            f"{json.dumps([_to_dict(item) for item in referenced_evidence], indent=2, default=str)}"
        )
        user_prompt = (
            user_prompt + "\n--- KNOWLEDGE BASE REFERENCES ---\n" + knowledge_block
        )
        response_text = llm.invoke([
            SystemMessage(content=OPERATIONAL_CLOSED_CASE_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ]).content
        if knowledge_docs:
            response_text = _inject_knowledge_refs(response_text, knowledge_docs)
        suggestions = extract_suggestions(response_text)
        return {
            "operational_draft": {
                "current_state": "closed",
                "current_state_recommendations": response_text,
                "next_state_preview": "",
                "supporting_cases": [_to_dict(c) for c in supporting_cases],
                "referenced_evidence": [_to_dict(e) for e in referenced_evidence],
                "suggestions": suggestions,
            },
            "_last_node": "operational_node",
        }

    # -- Active-case path --
    current_state = current_d_state or "D1_2"
    country = _extract_country(case_context)
    supporting_cases = search_similar_cases.invoke(
        {"query": question, "current_case_id": case_id, "country": country}
    )
    referenced_evidence = search_evidence.invoke({"case_id": case_id})

    formatted_d_states = format_d_states(case_context)
    formatted_supporting_cases = json.dumps(
        [_to_dict(item) for item in supporting_cases], indent=2, default=str
    )
    formatted_evidence = json.dumps(
        [_to_dict(item) for item in referenced_evidence], indent=2, default=str
    )
    user_prompt = (
        f"ACTIVE CASE: {case_id}\n"
        f"ACTIVE D-STATE: {current_state}\n"
        f"USER QUESTION: {question}\n"
        "\n--- CASE HISTORY ---\n"
        f"{formatted_d_states}\n"
        "\n--- SUPPORTING CLOSED CASES ---\n"
        f"{formatted_supporting_cases}\n"
        "\n--- REFERENCED EVIDENCE ---\n"
        f"{formatted_evidence}"
    )
    user_prompt = (
        user_prompt + "\n--- KNOWLEDGE BASE REFERENCES ---\n" + knowledge_block
    )

    response_text = llm.invoke([
        SystemMessage(content=OPERATIONAL_SYSTEM_PROMPT),
        HumanMessage(content=user_prompt),
    ]).content
    if knowledge_docs:
        response_text = _inject_knowledge_refs(response_text, knowledge_docs)

    suggestions = extract_suggestions(response_text)
    return {
        "operational_draft": {
            "current_state": current_state,
            "current_state_recommendations": response_text,
            "next_state_preview": "",
            "supporting_cases": [_to_dict(c) for c in supporting_cases],
            "referenced_evidence": [_to_dict(e) for e in referenced_evidence],
            "suggestions": suggestions,
        },
        "_last_node": "operational_node",
    }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _to_dict(obj: Any) -> dict:
    """Convert a Pydantic model or dict to a plain dict."""
    if isinstance(obj, dict):
        return obj
    # Use __iter__ for Pydantic v2 models (iterates field_name, value pairs)
    try:
        return dict(obj)
    except Exception:
        return vars(obj)


def _inject_knowledge_refs(response_text: str, knowledge_docs: list) -> str:
    """Insert [KNOWLEDGE REFERENCES] block before [WHAT TO EXPLORE NEXT] if present."""
    refs = build_refs_block(knowledge_docs)
    knowledge_section = "\n\n[KNOWLEDGE REFERENCES]\n" + refs
    explore_marker = "[WHAT TO EXPLORE NEXT]"
    if explore_marker in response_text:
        idx = response_text.index(explore_marker)
        return (
            response_text[:idx].rstrip()
            + knowledge_section
            + "\n\n"
            + response_text[idx:]
        )
    return response_text + knowledge_section


def _extract_country(case_context: dict[str, Any]) -> str | None:
    """Extract country from case context."""
    direct_country = case_context.get("organization_country")
    if isinstance(direct_country, str) and direct_country.strip():
        return direct_country.strip()
    d_states = normalize_d_states(case_context)
    if isinstance(d_states, dict):
        d12 = d_states.get("D1_2")
        if isinstance(d12, dict):
            data = d12.get("data")
            if isinstance(data, dict):
                country = data.get("country")
                if isinstance(country, str) and country.strip():
                    return country.strip()
    return None


