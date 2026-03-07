"""Langfuse tracing integration for CoSolve (v3 API).

Provides a singleton Langfuse client, span helpers, and score logging.
All functions degrade gracefully when Langfuse is not configured.
"""
from __future__ import annotations

import logging
import os

_logger = logging.getLogger(__name__)

# Module-level singleton — lazily initialised
_langfuse_client = None
_langfuse_checked = False


def _is_configured() -> bool:
    """Return True if Langfuse env vars are set with real values."""
    sk = os.getenv("LANGFUSE_SECRET_KEY", "")
    pk = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    if not sk or not pk:
        return False
    if sk.startswith("sk-lf-...") or pk.startswith("pk-lf-..."):
        return False
    return True


def get_langfuse():
    """Return the singleton Langfuse client, or None if not configured."""
    global _langfuse_client, _langfuse_checked
    if _langfuse_checked:
        return _langfuse_client
    _langfuse_checked = True
    if not _is_configured():
        return None
    try:
        from langfuse import Langfuse

        _langfuse_client = Langfuse()
        _logger.info("Langfuse client initialised")
    except Exception:
        _logger.debug("Failed to create Langfuse client", exc_info=True)
    return _langfuse_client


def start_trace(
    name: str = "cosolve-agent",
    session_id: str | None = None,
    user_id: str | None = None,
    metadata: dict | None = None,
):
    """Start a new Langfuse trace and return the span object (or None)."""
    lf = get_langfuse()
    if lf is None:
        return None
    try:
        return lf.start_span(
            name=name,
            metadata=metadata or {},
        )
    except Exception:
        _logger.debug("Failed to start Langfuse trace", exc_info=True)
        return None


def log_reflection_scores(
    trace_id: str,
    scores: dict[str, float],
    node_name: str = "",
) -> None:
    """Log reflection criterion scores to Langfuse.

    *scores* maps criterion names (e.g. ``"case_grounding"``) to float
    values in 0.0-1.0.  Silently skipped when Langfuse is not configured.
    """
    lf = get_langfuse()
    if lf is None:
        return
    try:
        for criterion, value in scores.items():
            lf.create_score(
                trace_id=trace_id,
                name=f"{node_name}.{criterion}" if node_name else criterion,
                value=value,
            )
    except Exception:
        _logger.debug("Failed to log reflection scores to Langfuse", exc_info=True)


def get_langfuse_handler(
    session_id: str | None = None,
    user_id: str | None = None,
    trace_name: str = "cosolve-agent",
    metadata: dict | None = None,
):
    """Return a configured Langfuse CallbackHandler for LangChain/LangGraph,
    or None if Langfuse is not configured.

    Compatible with Langfuse v3+.  Credentials are read from env vars
    (``LANGFUSE_SECRET_KEY``, ``LANGFUSE_PUBLIC_KEY``, ``LANGFUSE_HOST``).
    """
    secret_key = os.getenv("LANGFUSE_SECRET_KEY", "")
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "")

    if (not secret_key or not public_key
            or secret_key == "sk-lf-..."
            or public_key == "pk-lf-..."):
        return None

    try:
        from langfuse.callback import CallbackHandler

        handler = CallbackHandler()

        handler._cosolve_session_id = session_id
        handler._cosolve_user_id = user_id
        handler._cosolve_trace_name = trace_name
        handler._cosolve_metadata = metadata or {}

        return handler
    except Exception as exc:
        _logger.warning("Langfuse handler init failed: %s", exc)
        return None


def apply_trace_metadata(handler) -> None:
    """Tag the Langfuse trace created by the handler with session/user metadata.

    Uses the Langfuse ingestion API to upsert trace metadata by ``trace_id``.
    Does NOT require an active OTel span context — safe to call after
    ``graph.invoke()`` has returned.
    """
    if handler is None:
        return
    try:
        trace_id = getattr(handler, "last_trace_id", None)
        if not trace_id:
            return

        import requests
        from datetime import datetime, timezone

        host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com").rstrip("/")
        pk = os.getenv("LANGFUSE_PUBLIC_KEY", "")
        sk = os.getenv("LANGFUSE_SECRET_KEY", "")
        if not pk or not sk:
            return

        body: dict = {"id": trace_id}
        name = getattr(handler, "_cosolve_trace_name", None)
        if name:
            body["name"] = name
        session_id = getattr(handler, "_cosolve_session_id", None)
        if session_id:
            body["sessionId"] = session_id
        user_id = getattr(handler, "_cosolve_user_id", None)
        if user_id:
            body["userId"] = user_id
        metadata = getattr(handler, "_cosolve_metadata", None)
        if metadata:
            body["metadata"] = metadata

        requests.post(
            f"{host}/api/public/ingestion",
            json={
                "batch": [{
                    "id": f"{trace_id}-meta",
                    "type": "trace-create",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "body": body,
                }]
            },
            auth=(pk, sk),
            timeout=5,
        )
    except Exception as exc:
        _logger.debug("apply_trace_metadata skipped: %s", exc)


def flush_langfuse() -> None:
    """Flush any pending Langfuse events.  Safe to call even when not configured."""
    lf = get_langfuse()
    if lf is None:
        return
    try:
        lf.flush()
    except Exception:
        _logger.debug("Failed to flush Langfuse", exc_info=True)
