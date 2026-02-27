from __future__ import annotations

import logging
from typing import Callable

from pydantic import BaseModel

from backend.infra.llm_logging_client import LoggedLanguageModelClient

__all__ = ["BaseReflectionNode"]

_logger = logging.getLogger(__name__)


class BaseReflectionNode:
    """Shared scaffolding for all reflection nodes.

    Subclasses (or direct instantiations) supply:
      - reflection_prompt   – system prompt for the quality-audit LLM call
      - regeneration_prompt – system prompt for the rewrite LLM call
      - assessment_model    – Pydantic model that complete_json fills in
      - score_fn            – callable(assessment) -> float in [0.0, 1.0]
      - output_builder      – callable(draft_text, assessment) -> dict
    """

    _REGENERATION_THRESHOLD: float = 0.65

    def __init__(
        self,
        llm_client: LoggedLanguageModelClient,
        regeneration_llm_client: LoggedLanguageModelClient,
        reflection_prompt: str,
        regeneration_prompt: str,
        assessment_model: type[BaseModel],
        score_fn: Callable,
        output_builder: Callable,
    ) -> None:
        self._llm_client = llm_client
        self._regeneration_llm_client = regeneration_llm_client
        self._reflection_prompt = reflection_prompt
        self._regeneration_prompt = regeneration_prompt
        self._assessment_model = assessment_model
        self._score_fn = score_fn
        self._output_builder = output_builder

    def run(self, draft_text: str, question: str, case_id: str) -> dict:
        """Reflect on *draft_text*, optionally regenerate, then return built output.

        On any exception the original draft is returned unchanged as
        ``{"draft_text": draft_text}``.
        """
        try:
            assessment = self._llm_client.complete_json(
                system_prompt=self._reflection_prompt,
                user_prompt=(
                    f"question: {question}\n\n" f"draft_response:\n{draft_text}"
                ),
                response_model=self._assessment_model,
                temperature=0.0,
                user_question=question,
            )

            score = self._score_fn(assessment)

            final_draft = draft_text
            if score < self._REGENERATION_THRESHOLD:
                _logger.info(
                    "BaseReflectionNode: score %.3f below threshold %.3f for case %s"
                    " — triggering regeneration.",
                    score,
                    self._REGENERATION_THRESHOLD,
                    case_id,
                )
                final_draft = self._regeneration_llm_client.complete_text(
                    system_prompt=self._regeneration_prompt,
                    user_prompt=f"Question: {question}",
                    temperature=0.1,
                    user_question=question,
                )

            return self._output_builder(final_draft, assessment)

        except Exception as exc:  # noqa: BLE001
            _logger.exception(
                "BaseReflectionNode.run failed for case %s: %s", case_id, exc
            )
            return {"draft_text": draft_text}
