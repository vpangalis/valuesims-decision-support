from __future__ import annotations

import json
from typing import Any

from backend.config import Settings
from langchain_openai import AzureChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from backend.retrieval.hybrid_retriever import HybridRetriever
from backend.workflow.models import SimilarityPayload, SimilarityNodeOutput
from backend.workflow.nodes.node_parsing_utils import (
    extract_similarity_suggestions,
    format_d_states,
)
from backend.workflow.services.knowledge_formatter import knowledge_formatter
from backend.prompts import SIMILARITY_SYSTEM_PROMPT


class SimilarityNode:
    _SIMILARITY_SYSTEM_PROMPT = SIMILARITY_SYSTEM_PROMPT

    def __init__(
        self,
        hybrid_retriever: HybridRetriever,
        llm_client: AzureChatOpenAI,
        settings: Settings,
    ) -> None:
        self._hybrid_retriever = hybrid_retriever
        self._llm_client = llm_client
        self._settings = settings

    def run(
        self,
        question: str,
        case_id: str | None,
        country: str | None,
        case_context: dict[str, Any] | None = None,
        case_status: str | None = None,
    ) -> SimilarityNodeOutput:
        cases = self._hybrid_retriever.retrieve_similar_cases(
            query=question,
            current_case_id=case_id,
            country=country,
        )
        knowledge_docs = self._hybrid_retriever.retrieve_knowledge(
            query=question,
            top_k=4,
            cosolve_phase="root_cause",
        )

        # Build case context summary
        if case_context:
            case_context_summary = format_d_states(case_context)
        else:
            case_context_summary = (
                "No active case loaded — reasoning from question description only."
            )

        # Format retrieved cases
        supporting_cases_dicts = [item.model_dump(mode="json") for item in cases]
        if supporting_cases_dicts:
            formatted_cases = json.dumps(supporting_cases_dicts, indent=2, default=str)
        else:
            formatted_cases = "No cases retrieved from the knowledge base."

        if knowledge_docs:
            knowledge_block = "\n".join(
                f"Per {(item.source or item.doc_id)}"
                f"{(' [' + item.section_title + ']') if item.section_title else ''}: "
                f"{(item.content_text or '')[:600]}"
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

        response_text = self._llm_client.invoke([
            SystemMessage(content=SimilarityNode._SIMILARITY_SYSTEM_PROMPT),
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

        suggestions = extract_similarity_suggestions(response_text)

        return SimilarityNodeOutput(
            similarity_draft=SimilarityPayload(
                summary=response_text,
                supporting_cases=cases,
                suggestions=suggestions,
            )
        )

    def _extract_suggestions(self, response_text: str) -> list[dict]:
        """Delegate to the shared utility in node_parsing_utils."""
        return extract_similarity_suggestions(response_text)


__all__ = ["SimilarityNode"]
