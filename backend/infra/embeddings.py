from __future__ import annotations

import logging
import os
from typing import Any

from dotenv import load_dotenv
from openai import AzureOpenAI

logger = logging.getLogger("embeddings")


class EmbeddingClient:
    """Infrastructure client for generating embeddings.

    Supports two modes:
    - Injected client (openai_client + settings_module): used in tests / DI.
    - Lazy env-var client: built on the first call to generate_embedding(),
      after load_dotenv() has had a chance to populate os.environ.
    """

    def __init__(
        self, openai_client: Any | None = None, settings_module: Any | None = None
    ) -> None:
        self._openai_client = openai_client
        self._settings = settings_module
        # Lazily built AzureOpenAI client for the env-var path.
        self._lazy_client: AzureOpenAI | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_embedding(self, text: str) -> list[float]:
        logger.debug("[EMBED] generate_embedding called  input_len=%d", len(text or ""))

        if self._openai_client is not None:
            # Injected-client path (DI / tests).
            if self._settings is None:
                raise ValueError("Settings module is required for OpenAI embeddings.")
            embedding = (
                self._openai_client.embeddings.create(
                    model=self._settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
                    input=text,
                )
                .data[0]
                .embedding
            )
            logger.debug("[EMBED] embedding generated  len=%d", len(embedding))
            return embedding

        # Env-var path — build the client lazily on first use.
        client = self._get_lazy_client()
        deployment = os.environ.get("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "")
        if not deployment:
            raise ValueError("[EMBED] AZURE_OPENAI_EMBEDDING_DEPLOYMENT is not set.")
        response = client.embeddings.create(input=text, model=deployment)
        embedding = response.data[0].embedding
        logger.debug("[EMBED] embedding generated  len=%d", len(embedding))
        return embedding

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_lazy_client(self) -> AzureOpenAI:
        """Return (and cache) the AzureOpenAI client, reading env vars lazily.

        load_dotenv(override=True) is called here so that the client is always
        built after the .env file has been loaded, regardless of import order.
        """
        if self._lazy_client is not None:
            return self._lazy_client

        # Ensure .env values are present even if this runs before app startup.
        load_dotenv(override=True)

        endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
        api_key = os.environ.get("AZURE_OPENAI_API_KEY", "")
        api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")

        # Validate endpoint — surface misconfiguration immediately.
        if not endpoint:
            raise ValueError(
                "[EMBED] AZURE_OPENAI_ENDPOINT is not set. "
                "Check your .env file or environment variables."
            )
        if not endpoint.rstrip("/").endswith(".com"):
            raise ValueError(
                f"[EMBED] AZURE_OPENAI_ENDPOINT looks invalid: {endpoint!r}. "
                "Expected a URL ending with '.com' or '.com/'."
            )
        if not api_key:
            raise ValueError("[EMBED] AZURE_OPENAI_API_KEY is not set.")

        logger.info(
            "[EMBED] building AzureOpenAI client  endpoint=%r  api_version=%r",
            endpoint,
            api_version,
        )
        self._lazy_client = AzureOpenAI(
            api_key=api_key,
            api_version=api_version,
            azure_endpoint=endpoint,
        )
        return self._lazy_client
