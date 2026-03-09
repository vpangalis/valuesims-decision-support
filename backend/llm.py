# backend/llm.py
"""Single source of truth for all LangChain LLM instances.

All nodes import from here — never instantiate AzureChatOpenAI inline.
"""
from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv
from langchain_openai import AzureChatOpenAI

from backend.config import settings

load_dotenv(override=True)  # MUST use override=True — project requirement

# Role → Azure deployment name mapping
_ROLE_MAP: dict[str, str] = {
    "intent": settings.LLM_INTENT_DEPLOYMENT,
    "reasoning": settings.LLM_REASONING_DEPLOYMENT,
}


class LLMProvider:
    """Factory for cached AzureChatOpenAI instances."""

    @lru_cache(maxsize=16)
    def get_llm(
        self, deployment: str | None = None, temperature: float = 0.2
    ) -> AzureChatOpenAI:
        """Return a cached AzureChatOpenAI instance per (deployment, temperature) pair."""
        return AzureChatOpenAI(
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            azure_deployment=deployment or os.environ["AZURE_OPENAI_CHAT_DEPLOYMENT"],
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21"),
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
            temperature=temperature,
            max_retries=3,
        )


# ── Module-level singleton and shim (all existing callers unchanged) ──

_provider = LLMProvider()


def get_llm(
    role: str | None = None,
    temperature: float = 0.2,
    *,
    deployment: str | None = None,
) -> AzureChatOpenAI:
    """Resolve a logical role name to an Azure deployment and return a cached LLM.

    Roles:
      "intent"    — fast, cheap model for classification and routing
      "reasoning" — powerful model for analysis, reflection, formatting

    Falls back to treating the value as a literal deployment name for backwards compat.
    The ``deployment`` kwarg is kept for backwards compatibility with deprecated code.
    """
    name = role or deployment
    resolved = _ROLE_MAP.get(name, name) if name else None
    return _provider.get_llm(deployment=resolved, temperature=temperature)
