# backend/llm.py
"""Single source of truth for all LangChain LLM instances.

All nodes import from here — never instantiate AzureChatOpenAI inline.
"""
from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv
from langchain_openai import AzureChatOpenAI

load_dotenv(override=True)  # MUST use override=True — project requirement


@lru_cache(maxsize=16)
def get_llm(deployment: str | None = None, temperature: float = 0.2) -> AzureChatOpenAI:
    """Return a cached AzureChatOpenAI instance per (deployment, temperature) pair.

    Falls back to AZURE_OPENAI_CHAT_DEPLOYMENT if deployment is None or empty.
    """
    return AzureChatOpenAI(
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        azure_deployment=deployment or os.environ["AZURE_OPENAI_CHAT_DEPLOYMENT"],
        api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21"),
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        temperature=temperature,
        max_retries=3,
    )
