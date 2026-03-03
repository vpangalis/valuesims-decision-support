from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from backend.config import Settings
from backend.infra.language_model_client import LanguageModelClient

_LLM_LOG_PATH = Path("logs/llm_calls.jsonl")


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

    def _write_llm_log(self, record: dict) -> None:
        """Append one JSON record and prune entries older than 28 days.

        Reads the existing file, filters to the rolling 28-day window,
        appends the new record, then rewrites the file atomically.
        Silently ignores all I/O errors to avoid disrupting LLM calls.
        """
        try:
            _LLM_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            cutoff = datetime.now(timezone.utc) - timedelta(days=365)

            existing: list[dict] = []
            if _LLM_LOG_PATH.exists():
                with _LLM_LOG_PATH.open("r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                            ts = datetime.fromisoformat(entry.get("timestamp", ""))
                            if ts >= cutoff:
                                existing.append(entry)
                        except Exception:  # noqa: BLE001
                            pass  # skip malformed lines

            existing.append(record)

            with _LLM_LOG_PATH.open("w", encoding="utf-8") as f:
                for entry in existing:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:  # noqa: BLE001
            pass

    def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
        temperature: float = 0.1,
        user_question: str | None = None,
        model_name: str | None = None,
        model_name_override: str | None = None,
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
        )
        usage = getattr(self._base_client, "_last_usage", {})
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
                "completion_tokens": usage.get("completion_tokens"),
                "prompt_tokens": usage.get("prompt_tokens"),
                "total_tokens": usage.get("total_tokens"),
            },
        )
        self._write_llm_log(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "call_type": "json",
                "node_name": self._node_name,
                "model_name": effective_model_name,
                "response_time_ms": elapsed_ms,
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
                "prompt_characters": len(system_prompt) + len(user_prompt),
                "prompt_hash": prompt_hash,
                "temperature": temperature,
                "user_question": user_question,
            }
        )
        self._logger.info(
            "[LLM] %s | %s | %dms | prompt=%s completion=%s total=%s tokens",
            self._node_name,
            effective_model_name,
            round(elapsed_ms),
            usage.get("prompt_tokens"),
            usage.get("completion_tokens"),
            usage.get("total_tokens"),
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
        usage = getattr(self._base_client, "_last_usage", {})
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
                "completion_tokens": usage.get("completion_tokens"),
                "prompt_tokens": usage.get("prompt_tokens"),
                "total_tokens": usage.get("total_tokens"),
            },
        )
        self._write_llm_log(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "call_type": "text",
                "node_name": self._node_name,
                "model_name": effective_model_name,
                "response_time_ms": elapsed_ms,
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
                "prompt_characters": len(system_prompt) + len(user_prompt),
                "prompt_hash": prompt_hash,
                "temperature": temperature,
                "user_question": user_question,
            }
        )
        self._logger.info(
            "[LLM] %s | %s | %dms | prompt=%s completion=%s total=%s tokens",
            self._node_name,
            effective_model_name,
            round(elapsed_ms),
            usage.get("prompt_tokens"),
            usage.get("completion_tokens"),
            usage.get("total_tokens"),
        )
        return response


__all__ = ["LoggedLanguageModelClient"]
