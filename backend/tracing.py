"""Langfuse tracing integration for CoSolve (v3.14.5).

Uses the @observe decorator pattern — the correct approach for langfuse 3.14.5.
All functions degrade gracefully when Langfuse is not configured.
"""
from __future__ import annotations

import logging
import os

_logger = logging.getLogger(__name__)


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
    """Return a Langfuse client instance, or None if not configured."""
    if not _is_configured():
        return None
    try:
        from langfuse import Langfuse
        return Langfuse()
    except Exception:
        _logger.debug("Failed to create Langfuse client", exc_info=True)
        return None


def get_langfuse_handler(
    session_id: str | None = None,
    user_id: str | None = None,
    trace_name: str = "cosolve-agent",
    metadata: dict | None = None,
):
    """Return a configured Langfuse CallbackHandler, or None if not configured."""
    if not _is_configured():
        return None
    try:
        from langfuse.langchain import CallbackHandler
        public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "")
        handler = CallbackHandler(public_key=public_key)
        handler._cosolve_session_id = session_id
        handler._cosolve_user_id = user_id
        handler._cosolve_trace_name = trace_name
        handler._cosolve_metadata = metadata or {}
        return handler
    except Exception as exc:
        _logger.warning("Langfuse handler init failed: %s", exc)
        return None


def apply_trace_metadata(handler) -> None:
    """Tag the Langfuse trace with session/user metadata via ingestion API."""
    if handler is None:
        return
    try:
        trace_id = getattr(handler, "last_trace_id", None)
        if not trace_id:
            return
        import requests
        from datetime import datetime, timezone
        host = os.getenv("LANGFUSE_HOST",
                         os.getenv("LANGFUSE_BASE_URL",
                                   "https://cloud.langfuse.com")).rstrip("/")
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
            json={"batch": [{
                "id": f"{trace_id}-meta",
                "type": "trace-create",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "body": body,
            }]},
            auth=(pk, sk),
            timeout=5,
        )
    except Exception as exc:
        _logger.debug("apply_trace_metadata skipped: %s", exc)


def flush_langfuse() -> None:
    """Flush any pending Langfuse events."""
    lf = get_langfuse()
    if lf is None:
        return
    try:
        lf.flush()
    except Exception:
        _logger.debug("Failed to flush Langfuse", exc_info=True)
