from __future__ import annotations

import json
import logging
import os
from typing import Any, TypeVar

import requests
from pydantic import BaseModel, ValidationError


_logger = logging.getLogger(__name__)

TModel = TypeVar("TModel", bound=BaseModel)


class LanguageModelClient:
    """Infrastructure adapter for JSON-only LLM responses."""

    DEFAULT_API_VERSION = "2024-10-21"

    def __init__(
        self,
        openai_client: Any | None = None,
        settings_module: Any | None = None,
    ) -> None:
        self._openai_client = openai_client
        self._settings = settings_module
        self._last_usage: dict[str, int | None] = {
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
        }

    def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[TModel],
        temperature: float = 0.1,
        model_name: str | None = None,
    ) -> TModel:
        if self._openai_client is not None:
            content = self._complete_with_sdk(
                system_prompt,
                user_prompt,
                temperature,
                model_name,
            )
        else:
            content = self._complete_with_rest(
                system_prompt,
                user_prompt,
                temperature,
                model_name,
            )
        parsed = self._parse_json_content(content)
        try:
            return response_model.model_validate(parsed)
        except ValidationError as exc:
            _logger.warning(
                "LLM JSON validation failed for %s; attempting coercion. Error: %s",
                response_model.__name__,
                exc,
            )
            coerced = self._coerce_to_model(parsed, response_model)
            if coerced is not None:
                return coerced
            raise

    def _complete_with_sdk(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        model_name: str | None,
    ) -> str:
        if self._openai_client is None:
            raise ValueError("OpenAI client is not configured.")
        if self._settings is None:
            raise ValueError("Settings module is required for LLM calls.")
        deployment = model_name or getattr(
            self._settings,
            "AZURE_OPENAI_CHAT_DEPLOYMENT",
            "",
        )
        if not deployment:
            raise ValueError("AZURE_OPENAI_CHAT_DEPLOYMENT is not configured.")
        response = self._openai_client.chat.completions.create(
            model=deployment,
            response_format={"type": "json_object"},
            temperature=temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = response.choices[0].message.content
        usage = getattr(response, "usage", None)
        self._last_usage = {
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
        }
        if not content:
            raise ValueError("LLM returned empty response content.")
        return str(content)

    def _complete_with_rest(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        model_name: str | None,
    ) -> str:
        endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
        api_key = os.environ.get("AZURE_OPENAI_API_KEY")
        deployment = model_name or os.environ.get("AZURE_OPENAI_CHAT_DEPLOYMENT")
        api_version = os.environ.get(
            "AZURE_OPENAI_API_VERSION", self.DEFAULT_API_VERSION
        )

        if not endpoint or not api_key or not deployment:
            raise ValueError("Azure OpenAI chat configuration is missing.")

        url = (
            f"{endpoint.rstrip('/')}/openai/deployments/{deployment}/chat/completions"
            f"?api-version={api_version}"
        )
        payload = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Content-Type": "application/json",
            "api-key": api_key,
        }
        print(
            f"[DEBUG LLM URL] url={url!r} deployment={deployment!r} api_version={api_version!r}"
        )
        response = requests.post(url, headers=headers, json=payload, timeout=45)
        if response.status_code != 200:
            raise RuntimeError(f"LLM request failed: {response.text}")
        data = response.json()
        usage = data.get("usage") or {}
        self._last_usage = {
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
        }
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("LLM request returned no choices.")
        message = (choices[0].get("message") or {}).get("content")
        if not message:
            raise RuntimeError("LLM response content was empty.")
        return str(message)

    def complete_text(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        model_name: str | None = None,
    ) -> str:
        if self._openai_client is not None:
            return self._complete_text_with_sdk(
                system_prompt, user_prompt, temperature, model_name
            )
        return self._complete_text_with_rest(
            system_prompt, user_prompt, temperature, model_name
        )

    def _complete_text_with_sdk(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        model_name: str | None,
    ) -> str:
        if self._openai_client is None:
            raise ValueError("OpenAI client is not configured.")
        if self._settings is None:
            raise ValueError("Settings module is required for LLM calls.")
        deployment = model_name or getattr(
            self._settings, "AZURE_OPENAI_CHAT_DEPLOYMENT", ""
        )
        if not deployment:
            raise ValueError("AZURE_OPENAI_CHAT_DEPLOYMENT is not configured.")
        response = self._openai_client.chat.completions.create(
            model=deployment,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = response.choices[0].message.content
        usage = getattr(response, "usage", None)
        self._last_usage = {
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
        }
        if not content:
            raise ValueError("LLM returned empty response content.")
        return str(content)

    def _complete_text_with_rest(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        model_name: str | None,
    ) -> str:
        endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
        api_key = os.environ.get("AZURE_OPENAI_API_KEY")
        deployment = model_name or os.environ.get("AZURE_OPENAI_CHAT_DEPLOYMENT")
        api_version = os.environ.get(
            "AZURE_OPENAI_API_VERSION", self.DEFAULT_API_VERSION
        )
        if not endpoint or not api_key or not deployment:
            raise ValueError("Azure OpenAI chat configuration is missing.")
        url = (
            f"{endpoint.rstrip('/')}/openai/deployments/{deployment}/chat/completions"
            f"?api-version={api_version}"
        )
        payload = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
        }
        headers = {
            "Content-Type": "application/json",
            "api-key": api_key,
        }
        response = requests.post(url, headers=headers, json=payload, timeout=45)
        if response.status_code != 200:
            raise RuntimeError(f"LLM request failed: {response.text}")
        data = response.json()
        usage = data.get("usage") or {}
        self._last_usage = {
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
        }
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("LLM request returned no choices.")
        message = (choices[0].get("message") or {}).get("content")
        if not message:
            raise RuntimeError("LLM response content was empty.")
        return str(message)

    def _coerce_to_model(
        self, parsed: dict[str, Any], response_model: type[TModel]
    ) -> TModel | None:
        """Best-effort coercion when the LLM returns unexpected JSON keys.

        Strategy:
        1. For each required string field in the target model that is missing
           from the parsed dict, look for any string value in the parsed dict
           to substitute.  If nothing matches, serialise the whole dict as
           a JSON string.
        2. Try model_validate on the patched dict.  Return None on failure so
           the caller can re-raise the original ValidationError.
        """
        try:
            fields = response_model.model_fields
            patched = dict(parsed)

            # Collect top-level string values from the LLM response as candidates
            string_candidates: list[str] = []
            for v in parsed.values():
                if isinstance(v, str) and v.strip():
                    string_candidates.append(v)
                elif isinstance(v, dict):
                    # Flatten one level deep
                    string_candidates.extend(
                        sv for sv in v.values() if isinstance(sv, str) and sv.strip()
                    )

            fallback_text = (
                string_candidates[0]
                if string_candidates
                else json.dumps(parsed, ensure_ascii=False)
            )

            for field_name, field_info in fields.items():
                if field_name in patched:
                    continue
                # Determine if the field annotation is (or includes) str
                annotation = field_info.annotation
                is_str_field = annotation is str or (
                    hasattr(annotation, "__args__")
                    and str in getattr(annotation, "__args__", ())
                )
                if is_str_field:
                    patched[field_name] = fallback_text

            return response_model.model_validate(patched)
        except Exception:
            return None

    def _parse_json_content(self, content: str) -> dict[str, Any]:
        normalized = content.strip()
        if normalized.startswith("```"):
            normalized = normalized.strip("`")
            if normalized.startswith("json"):
                normalized = normalized[4:].strip()
        payload = json.loads(normalized)
        if not isinstance(payload, dict):
            raise ValueError("LLM response JSON must be an object.")
        return payload


__all__ = ["LanguageModelClient"]
