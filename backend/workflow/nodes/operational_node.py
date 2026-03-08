from __future__ import annotations

import json
from typing import Any

from backend.config import Settings
from backend.llm import get_llm
from langchain_openai import AzureChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from backend.retrieval.hybrid_retriever import HybridRetriever
from backend.workflow.models import (
    OperationalPayload,
    OperationalNodeOutput,
)
from backend.workflow.nodes.node_parsing_utils import (
    NEW_PROBLEM_KEYWORDS,
    extract_suggestions,
    format_d_states,
    is_new_problem_question,
    normalize_d_states,
)
from backend.workflow.services.knowledge_formatter import knowledge_formatter
from backend.prompts import (
    OPERATIONAL_NEW_PROBLEM_SYSTEM_PROMPT,
    OPERATIONAL_SYSTEM_PROMPT,
    OPERATIONAL_CLOSED_CASE_SYSTEM_PROMPT,
)


class OperationalNode:

    _NEW_PROBLEM_SYSTEM_PROMPT = OPERATIONAL_NEW_PROBLEM_SYSTEM_PROMPT
    _OPERATIONAL_SYSTEM_PROMPT = OPERATIONAL_SYSTEM_PROMPT
    _CLOSED_CASE_SYSTEM_PROMPT = OPERATIONAL_CLOSED_CASE_SYSTEM_PROMPT

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
        case_id: str,
        case_context: dict[str, Any],
        current_d_state: str | None,
        model_name: str | None = None,
        case_status: str | None = None,
    ) -> OperationalNodeOutput:
        llm = self._resolve_llm(model_name)
        op_phase = "root_cause" if case_status == "open" else "general"
        knowledge_docs = self._hybrid_retriever.retrieve_knowledge(
            query=question,
            top_k=4,
            cosolve_phase=op_phase,
        )
        if knowledge_docs:
            knowledge_block = "\n".join(
                f"Per {(item.source or item.doc_id)}"
                f"{(' [' + item.section_title + ']') if item.section_title else ''}: "
                f"{(item.content_text or '')[:600]}"
                for item in knowledge_docs
            )
        else:
            knowledge_block = "No relevant knowledge documents found for this case."

        # Route new-problem questions (no case loaded) to a dedicated prompt so the
        # LLM is not confused by the "embedded in an active case" framing.
        if is_new_problem_question(question, case_id):
            user_prompt = f"USER QUESTION: {question}"
            user_prompt = (
                user_prompt + "\n--- KNOWLEDGE BASE REFERENCES ---\n" + knowledge_block
            )
            response_text = llm.invoke([
                SystemMessage(content=OperationalNode._NEW_PROBLEM_SYSTEM_PROMPT),
                HumanMessage(content=user_prompt),
            ]).content
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
            suggestions = extract_suggestions(response_text)
            return OperationalNodeOutput(
                operational_draft=OperationalPayload(
                    current_state="No case loaded",
                    current_state_recommendations=response_text,
                    next_state_preview="",
                    supporting_cases=[],
                    referenced_evidence=[],
                    suggestions=suggestions,
                )
            )

        # Closed case path: summarise history without suggesting next steps.
        # Skip the escalation quality gate — historical summaries need no re-check.
        if case_status == "closed" and case_id:
            supporting_cases = self._hybrid_retriever.retrieve_similar_cases(
                query=question,
                current_case_id=case_id,
                country=self._extract_country(case_context),
            )
            referenced_evidence = self._hybrid_retriever.retrieve_evidence_for_case(
                case_id=case_id,
            )
            user_prompt = (
                f"CLOSED CASE: {case_id}\n"
                f"USER QUESTION: {question}\n"
                "\n--- CASE HISTORY ---\n"
                f"{format_d_states(case_context)}\n"
                "\n--- SUPPORTING CLOSED CASES ---\n"
                f"{json.dumps([item.model_dump(mode='json') for item in supporting_cases], indent=2)}\n"
                "\n--- REFERENCED EVIDENCE ---\n"
                f"{json.dumps([item.model_dump(mode='json') for item in referenced_evidence], indent=2)}"
            )
            user_prompt = (
                user_prompt + "\n--- KNOWLEDGE BASE REFERENCES ---\n" + knowledge_block
            )
            response_text = llm.invoke([
                SystemMessage(content=OperationalNode._CLOSED_CASE_SYSTEM_PROMPT),
                HumanMessage(content=user_prompt),
            ]).content
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
            suggestions = extract_suggestions(response_text)
            return OperationalNodeOutput(
                operational_draft=OperationalPayload(
                    current_state="closed",
                    current_state_recommendations=response_text,
                    next_state_preview="",
                    supporting_cases=supporting_cases,
                    referenced_evidence=referenced_evidence,
                    suggestions=suggestions,
                )
            )

        current_state = current_d_state or "D1_2"
        country = self._extract_country(case_context)
        supporting_cases = self._hybrid_retriever.retrieve_similar_cases(
            query=question,
            current_case_id=case_id,
            country=country,
        )
        referenced_evidence = self._hybrid_retriever.retrieve_evidence_for_case(
            case_id=case_id,
        )
        user_prompt = self._build_structured_prompt(
            case_context=case_context,
            case_id=case_id,
            question=question,
            current_state=current_state,
            supporting_cases=supporting_cases,
            referenced_evidence=referenced_evidence,
        )
        user_prompt = (
            user_prompt + "\n--- KNOWLEDGE BASE REFERENCES ---\n" + knowledge_block
        )

        response_text = llm.invoke([
            SystemMessage(content=OperationalNode._OPERATIONAL_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ]).content
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

        # FIX 1: next_state_preview is suppressed as a separate field.
        # The full response_text already contains [NEXT STATE PREVIEW] inline;
        # rendering it separately caused the section to appear twice in the UI.
        suggestions = extract_suggestions(response_text)
        return OperationalNodeOutput(
            operational_draft=OperationalPayload(
                current_state=current_state,
                current_state_recommendations=response_text,
                next_state_preview="",
                supporting_cases=supporting_cases,
                referenced_evidence=referenced_evidence,
                suggestions=suggestions,
            )
        )

    def _extract_country(self, case_context: dict[str, Any]) -> str | None:
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

    def _build_structured_prompt(
        self,
        case_context: dict[str, Any],
        case_id: str,
        question: str,
        current_state: str,
        supporting_cases: list[Any],
        referenced_evidence: list[Any],
    ) -> str:
        formatted_d_states = format_d_states(case_context)
        formatted_supporting_cases = json.dumps(
            [item.model_dump(mode="json") for item in supporting_cases], indent=2
        )
        formatted_evidence = json.dumps(
            [item.model_dump(mode="json") for item in referenced_evidence], indent=2
        )
        return (
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


__all__ = ["OperationalNode"]
