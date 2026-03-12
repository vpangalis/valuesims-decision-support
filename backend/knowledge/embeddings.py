"""Unified embedding layer — thin wrapper around LangChain AzureOpenAIEmbeddings.

get_embeddings()      → singleton AzureOpenAIEmbeddings instance
generate_embedding()  → convenience shim returning list[float]
"""
from __future__ import annotations

import logging
import os
from functools import lru_cache

from dotenv import load_dotenv
from langchain_openai import AzureOpenAIEmbeddings

logger = logging.getLogger("embeddings")


@lru_cache(maxsize=1)
def get_embeddings() -> AzureOpenAIEmbeddings:
    """Return a cached AzureOpenAIEmbeddings instance.

    load_dotenv(override=True) is called here so the singleton is always
    built after the .env file has been loaded, regardless of import order.
    """
    load_dotenv(override=True)

    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
    api_key = os.environ.get("AZURE_OPENAI_API_KEY", "")
    deployment = os.environ.get("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "")
    api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")

    if not endpoint:
        raise ValueError("[EMBED] AZURE_OPENAI_ENDPOINT is not set.")
    if not api_key:
        raise ValueError("[EMBED] AZURE_OPENAI_API_KEY is not set.")
    if not deployment:
        raise ValueError("[EMBED] AZURE_OPENAI_EMBEDDING_DEPLOYMENT is not set.")

    logger.info(
        "[EMBED] building AzureOpenAIEmbeddings  endpoint=%r  deployment=%r",
        endpoint,
        deployment,
    )
    return AzureOpenAIEmbeddings(
        azure_endpoint=endpoint,
        azure_deployment=deployment,
        api_key=api_key,
        api_version=api_version,
    )


def generate_embedding(text: str) -> list[float]:
    """Generate an embedding vector for *text*.

    Drop-in replacement for the old EmbeddingClient.generate_embedding().
    """
    result = get_embeddings().embed_query(text or "")
    logger.debug("[EMBED] embedding generated  len=%d", len(result))
    return result


__all__ = ["get_embeddings", "generate_embedding"]
