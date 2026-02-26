from __future__ import annotations

import hashlib
import logging
import time
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

from backend.config import Settings
from backend.infra.language_model_client import LanguageModelClient


class LoggedLanguageModelClient:
    def __init__(
        self,
        base_client: LanguageModelClient,
        settings: Settings,
        node_name: str,
        model_name: str | None = None,
    ) -> None:
        self._base_client = base_client
        self._settings = settings
        self._node_name = node_name
        self._model_name = model_name or settings.AZURE_OPENAI_CHAT_DEPLOYMENT
        self._logger = logging.getLogger("llm_prompt_logger")

    def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
        temperature: float = 0.1,
        user_question: str | None = None,
        model_name: str | None = None,
        model_name_override: str | None = None,
        max_tokens: int | None = None,
    ) -> Any:
        effective_model_name = model_name or model_name_override or self._model_name
        prompt_hash = hashlib.sha256(
            f"{system_prompt}\n---\n{user_prompt}".encode("utf-8")
        ).hexdigest()
        started = time.perf_counter()
        response = self._base_client.complete_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=response_model,
            temperature=temperature,
            model_name=effective_model_name,
            max_tokens=max_tokens,
        )
        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)

        self._logger.info(
            "llm_request",
            extra={
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "node_name": self._node_name,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "model_name": effective_model_name,
                "prompt_hash": prompt_hash,
                "response_time": elapsed_ms,
                "user_question": user_question,
                "temperature": temperature,
                "prompt_characters": len(system_prompt) + len(user_prompt),
                "completion_tokens": None,
                "prompt_tokens": None,
                "total_tokens": None,
            },
        )
        return response

    def complete_text(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        user_question: str | None = None,
        model_name: str | None = None,
    ) -> str:
        effective_model_name = model_name or self._model_name
        prompt_hash = hashlib.sha256(
            f"{system_prompt}\n---\n{user_prompt}".encode("utf-8")
        ).hexdigest()
        started = time.perf_counter()
        response = self._base_client.complete_text(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            model_name=effective_model_name,
        )
        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
        self._logger.info(
            "llm_request",
            extra={
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "node_name": self._node_name,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "model_name": effective_model_name,
                "prompt_hash": prompt_hash,
                "response_time": elapsed_ms,
                "user_question": user_question,
                "temperature": temperature,
                "prompt_characters": len(system_prompt) + len(user_prompt),
                "completion_tokens": None,
                "prompt_tokens": None,
                "total_tokens": None,
            },
        )
        return response


__all__ = ["LoggedLanguageModelClient"]
