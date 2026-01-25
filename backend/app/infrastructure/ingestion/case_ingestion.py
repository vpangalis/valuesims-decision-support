from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime
from typing import Any, Iterable

import requests
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
from azure.search.documents import SearchClient

from app.config import settings
from app.domain.case.models import CaseModel
from app.infrastructure.search.case_index import (
    CASE_INDEX_NAME,
    build_doc_id,
    validate_doc_id,
)
from app.infrastructure.storage.blob_client import AzureBlobClient

logger = logging.getLogger("case_ingestion")

CASES_PREFIX = "cases/"
CASE_JSON_SUFFIX = "/case.json"

# Embeddings are generated via Azure OpenAI and must not be regenerated for v1.
# Hybrid scoring weighting is configured at the search service layer only.
# Dev/Test/Prod must use isolated Search services or distinct index names.


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _log_outcome(status: str, case_id: str, reason: str | None = None) -> None:
    payload = {
        "timestamp": _now_iso(),
        "case_id": case_id,
        "status": status,
    }
    if reason:
        payload["reason"] = reason
    logger.info(json.dumps(payload))


def _list_case_json_paths(blob: AzureBlobClient) -> list[str]:
    files = blob.list_files(CASES_PREFIX)
    return [f["name"] for f in files if f["name"].endswith(CASE_JSON_SUFFIX)]


def _extract_case_id(path: str) -> str:
    # Path format: cases/{case_id}/case.json
    parts = path.split("/")
    if len(parts) < 3 or parts[0] != "cases" or parts[-1] != "case.json":
        raise ValueError(f"Invalid case path: {path}")
    return parts[1]


def _safe_get(data: dict, *keys: str, default: Any = "") -> Any:
    cur: Any = data
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def _flatten(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, list):
            result.extend([str(v) for v in value if v not in (None, "")])
        elif value != "":
            result.append(str(value))
    return result


def _join_text(values: Iterable[Any]) -> str:
    parts = [str(v).strip() for v in _flatten(values) if str(v).strip()]
    return "\n".join(parts)


def _join_dict_field(values: Iterable[Any], field: str) -> str:
    items: list[str] = []
    for value in values:
        if isinstance(value, dict) and field in value:
            items.append(str(value.get(field, "")).strip())
    return _join_text(items)


def _collect_discipline_completed(phases: dict[str, Any]) -> list[str]:
    completed: list[str] = []
    for phase_key, phase in phases.items():
        header = phase.get("header", {}) if isinstance(phase, dict) else {}
        if not header.get("completed"):
            continue
        discipline = header.get("discipline")
        if isinstance(discipline, list):
            completed.extend([str(d) for d in discipline])
        elif discipline:
            completed.append(str(discipline))
    return completed


def _build_searchable_fields(case_doc: dict[str, Any]) -> dict[str, Any]:
    phases = case_doc.get("phases", {})
    evidence = case_doc.get("evidence", [])
    ai = case_doc.get("ai", {}) or {}

    fishbone = _safe_get(phases, "D5", "data", "fishbone", default={})
    fishbone_text = _join_text(
        _flatten([fishbone.get(k, []) for k in fishbone.keys()])
    )

    five_whys = _safe_get(phases, "D5", "data", "five_whys", default={})
    five_whys_text = _join_text(
        [five_whys.get("A", []), five_whys.get("B", [])]
    )

    evidence_descriptions = _join_text([e.get("description", "") for e in evidence])
    evidence_tags = _flatten([e.get("tags", []) for e in evidence])

    return {
        "problem_description": _safe_get(
            phases, "D1_D2", "data", "problem_description"
        ),
        "team_members": _safe_get(phases, "D1_D2", "data", "team_members", default=[]),
        "what_happened": _safe_get(phases, "D3", "data", "what_happened"),
        "why_problem": _safe_get(phases, "D3", "data", "why_problem"),
        "when": _safe_get(phases, "D3", "data", "when"),
        "where": _safe_get(phases, "D3", "data", "where"),
        "who": _safe_get(phases, "D3", "data", "who"),
        "how_identified": _safe_get(phases, "D3", "data", "how_identified"),
        "impact": _safe_get(phases, "D3", "data", "impact"),
        "immediate_actions_text": _join_dict_field(
            _safe_get(phases, "D4", "data", "actions", default=[]), "action"
        ),
        "permanent_actions_text": _join_dict_field(
            _safe_get(phases, "D6", "data", "actions", default=[]), "action"
        ),
        "investigation_tasks_text": _join_dict_field(
            _safe_get(phases, "D5", "data", "investigation_tasks", default=[]),
            "task",
        ),
        "factors_text": _join_dict_field(
            _safe_get(phases, "D5", "data", "factors", default=[]), "factor"
        ),
        "fishbone_text": fishbone_text,
        "five_whys_text": five_whys_text,
        "evidence_descriptions": evidence_descriptions,
        "evidence_tags": evidence_tags,
        "ai_summary": ai.get("summary", ""),
    }


def _build_embedding_input(searchable_fields: dict[str, Any]) -> str:
    # Embeddings use approved textual fields only. Do not embed raw JSON or blobs.
    parts: list[str] = []
    for key, value in searchable_fields.items():
        if isinstance(value, list):
            parts.append(_join_text(value))
        else:
            parts.append(str(value))
    return _join_text(parts)


def _searchable_hash(searchable_fields: dict[str, Any]) -> str:
    payload = json.dumps(searchable_fields, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _existing_doc_hash(client: SearchClient, doc_id: str) -> str | None:
    try:
        doc = client.get_document(key=doc_id)
    except ResourceNotFoundError:
        return None

    existing_searchable = {
        key: doc.get(key)
        for key in [
            "problem_description",
            "team_members",
            "what_happened",
            "why_problem",
            "when",
            "where",
            "who",
            "how_identified",
            "impact",
            "immediate_actions_text",
            "permanent_actions_text",
            "investigation_tasks_text",
            "factors_text",
            "fishbone_text",
            "five_whys_text",
            "evidence_descriptions",
            "evidence_tags",
            "ai_summary",
        ]
    }
    return _searchable_hash(existing_searchable)


def _generate_embedding(text: str) -> list[float]:
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    deployment = os.environ.get("AZURE_OPENAI_EMBEDDING_DEPLOYMENT")
    api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")

    if not endpoint or not api_key or not deployment:
        raise ValueError("Azure OpenAI embedding configuration is missing.")

    url = f"{endpoint.rstrip('/')}/openai/deployments/{deployment}/embeddings?api-version={api_version}"
    headers = {
        "Content-Type": "application/json",
        "api-key": api_key,
    }
    payload = {
        "input": text,
    }
    response = requests.post(url, headers=headers, json=payload, timeout=30)
    if response.status_code != 200:
        raise RuntimeError(f"Embedding request failed: {response.text}")
    body = response.json()
    return body["data"][0]["embedding"]


def _build_index_document(case_doc: dict[str, Any], doc_id: str) -> dict[str, Any]:
    case = case_doc["case"]
    phases = case_doc.get("phases", {})
    searchable_fields = _build_searchable_fields(case_doc)

    document: dict[str, Any] = {
        "doc_id": doc_id,
        "case_id": case.get("case_number"),
        "status": case.get("status"),
        "opening_date": case.get("opening_date"),
        "closure_date": case.get("closure_date")
        or _safe_get(phases, "D8", "data", "closure_date", default=None),
        "created_at": _safe_get(case_doc, "meta", "created_at", default=None),
        "updated_at": _safe_get(case_doc, "meta", "updated_at", default=None),
        "version": _safe_get(case_doc, "meta", "version", default=1),
        "organization_country": _safe_get(
            phases, "D1_D2", "data", "organization", "country"
        ),
        "organization_site": _safe_get(
            phases, "D1_D2", "data", "organization", "site"
        ),
        "organization_department": _safe_get(
            phases, "D1_D2", "data", "organization", "department"
        ),
        "discipline_completed": _collect_discipline_completed(phases),
    }

    document.update(searchable_fields)
    return document


def _validate_closed_case(case_doc: CaseModel) -> bool:
    return case_doc.case.status == "closed"


def ingest_closed_case(client: SearchClient, blob: AzureBlobClient, path: str) -> None:
    case_id = _extract_case_id(path)

    try:
        raw = blob.download_json(path)
        data = json.loads(raw)
        case_model = CaseModel.model_validate(data)
    except Exception as exc:
        _log_outcome("FAILED", case_id, f"schema_validation_error: {exc}")
        return

    if not _validate_closed_case(case_model):
        _log_outcome("SKIPPED", case_id, "status_not_closed")
        return

    doc_id = build_doc_id(case_id)
    validate_doc_id(doc_id)

    searchable_fields = _build_searchable_fields(case_model.model_dump())
    new_hash = _searchable_hash(searchable_fields)
    existing_hash = _existing_doc_hash(client, doc_id)

    if existing_hash is not None:
        if existing_hash == new_hash:
            _log_outcome("SKIPPED", case_id, "content_hash_unchanged")
            return
        # Closed cases are immutable in Sprint 3; do not regenerate embeddings.
        _log_outcome("FAILED", case_id, "content_hash_changed_for_closed_case")
        return

    embedding_input = _build_embedding_input(searchable_fields)
    if not embedding_input:
        _log_outcome("FAILED", case_id, "empty_embedding_input")
        return

    try:
        embedding = _generate_embedding(embedding_input)
    except Exception as exc:
        _log_outcome("FAILED", case_id, f"embedding_failed: {exc}")
        return

    document = _build_index_document(case_model.model_dump(), doc_id)
    document["content_vector"] = embedding

    try:
        client.upload_documents([document])
    except HttpResponseError as exc:
        _log_outcome("FAILED", case_id, f"index_upsert_failed: {exc}")
        return

    _log_outcome("SUCCESS", case_id)


def ingest_all_closed_cases() -> None:
    # Index name is immutable for Sprint 3; use case_index_v2 for schema changes.
    if os.getenv("AZURE_SEARCH_INDEX_NAME"):
        raise ValueError(
            "AZURE_SEARCH_INDEX_NAME overrides are not allowed for Sprint 3."
        )

    blob_client = AzureBlobClient(
        settings.AZURE_STORAGE_CONNECTION_STRING,
        settings.AZURE_STORAGE_CONTAINER,
    )

    search_client = SearchClient(
        endpoint=settings.AZURE_SEARCH_ENDPOINT,
        index_name=CASE_INDEX_NAME,
        credential=AzureKeyCredential(settings.AZURE_SEARCH_ADMIN_KEY),
    )

    paths = _list_case_json_paths(blob_client)
    for path in paths:
        ingest_closed_case(search_client, blob_client, path)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ingest_all_closed_cases()
    # Manual invocation: python -m app.infrastructure.ingestion.case_ingestion
