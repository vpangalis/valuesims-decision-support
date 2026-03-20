from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from backend.core.state import IncidentGraphState

_CASE_ID_RE = re.compile(r"TRM-\d{8}-\d{4}")
from backend.core.config import Settings
from backend.storage.blob_storage import BlobStorageClient, CaseRepository
from backend.storage.ingestion.case_ingestion import CaseEntryService


@lru_cache(maxsize=1)
def _get_case_entry_service() -> CaseEntryService:
    s = Settings()
    blob = BlobStorageClient(
        s.AZURE_STORAGE_CONNECTION_STRING,
        s.AZURE_STORAGE_CONTAINER,
    )
    repo = CaseRepository(blob)
    return CaseEntryService(repo)


def context_node(state: IncidentGraphState) -> dict:
    """Load case context from blob storage if a case_id is present."""
    case_id = state.get("case_id")
    if not case_id:
        question = state.get("question") or ""
        has_case_id = bool(_CASE_ID_RE.search(question))
        return {
            "case_context": None,
            "current_d_state": None,
            "case_id_in_question": has_case_id,
            "_last_node": "context_node",
        }

    try:
        case_doc = _get_case_entry_service().get_case(case_id)
    except FileNotFoundError:
        return {
            "case_context": None,
            "current_d_state": None,
            "_last_node": "context_node",
        }

    return {
        "case_context": case_doc,
        "case_status": case_doc.get("case_status"),
        "current_d_state": _detect_current_state(case_doc),
        "_last_node": "context_node",
    }


def _detect_current_state(case_doc: dict[str, Any]) -> str | None:
    """Detect the most advanced D-state from the case document."""
    reasoning_state = case_doc.get("reasoning_state")
    if not isinstance(reasoning_state, dict):
        reasoning_state = case_doc.get("d_states")
    if not isinstance(reasoning_state, dict):
        phases = case_doc.get("phases")
        if isinstance(phases, dict) and phases:
            reasoning_state = {
                ("D1_2" if k == "D1_D2" else k): v for k, v in phases.items()
            }
    if not isinstance(reasoning_state, dict):
        return None

    progression = ["D8", "D7", "D6", "D5", "D4", "D3", "D1_2"]
    for key in progression:
        block = reasoning_state.get(key)
        if not isinstance(block, dict):
            continue
        header = block.get("header")
        if isinstance(header, dict) and header.get("completed"):
            return key
        status = str(block.get("status") or "").lower()
        has_data = isinstance(block.get("data"), dict) and bool(block.get("data"))
        if status in {"in_progress", "completed"} or has_data:
            return key
    return "D1_2"


