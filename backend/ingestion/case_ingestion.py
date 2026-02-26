from __future__ import annotations

import copy
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Iterable

from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import ResourceNotFoundError
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import SearchIndex

from backend.state.incident_state import (
    IncidentFactory,
    LegacyCaseModel,
    IncidentStateAdapter,
)
from backend.infra.embeddings import EmbeddingClient
from backend.infra.blob_storage import CaseReadRepository, CaseRepository


class CaseSearchIndex:
    """Thin adapter over Azure AI Search for case indexing."""

    def __init__(self, endpoint: str, index_name: str, admin_key: str) -> None:
        self._endpoint = endpoint
        self._index_name = index_name
        self._admin_key = admin_key
        self._credential = AzureKeyCredential(admin_key)
        self._search_client = SearchClient(
            endpoint=endpoint,
            index_name=index_name,
            credential=self._credential,
        )
        self._index_client = SearchIndexClient(
            endpoint=endpoint,
            credential=self._credential,
        )

    def get_document(self, doc_id: str) -> dict[str, object]:
        return self._search_client.get_document(key=doc_id)

    @property
    def index_name(self) -> str:
        return self._index_name

    def get_doc_id_suffix(self) -> str:
        return f"__{self._index_name}"

    def try_get_document(self, doc_id: str) -> dict[str, object] | None:
        try:
            return self.get_document(doc_id)
        except ResourceNotFoundError:
            return None

    def get_index(self, index_name: str) -> SearchIndex:
        return self._index_client.get_index(index_name)

    def upload_documents(self, documents: list[dict]) -> list:
        if not isinstance(documents, list):
            raise TypeError(
                f"upload_documents expects list[dict], got {type(documents).__name__}"
            )
        return self._search_client.upload_documents(documents=documents)

    def merge_or_upload_documents(self, documents: list[dict]) -> list:
        """Upsert documents — create if new, update if already indexed."""
        if not isinstance(documents, list):
            raise TypeError(
                f"merge_or_upload_documents expects list[dict], got {type(documents).__name__}"
            )
        return self._search_client.merge_or_upload_documents(documents=documents)


class CaseEntryService:
    def __init__(self, repository: CaseRepository):
        self._repo = repository

    def create_case(self, case_id: str, opened_at: str | None = None) -> dict:
        if self._repo.exists(case_id):
            raise ValueError("Case already exists")
        doc = IncidentFactory.create_empty(case_id, opened_at)
        self._repo.create(case_id, doc)
        return doc

    def load_case(self, case_id: str) -> dict:
        return self._repo.load(case_id)

    def get_case(self, case_id: str) -> dict:
        if not self._repo.exists(case_id):
            raise FileNotFoundError("Case not found")
        # Return the full canonical document exactly as stored.
        return copy.deepcopy(self._repo.load(case_id))

    def patch_case(self, case_id: str, patch: dict) -> dict:
        if not self._repo.exists(case_id):
            raise FileNotFoundError("Case not found")
        current = self._repo.load(case_id)
        self._validate_patch(current, patch)
        updated = self._deep_merge(current, patch)
        meta = updated.get("meta", {})
        meta["updated_at"] = self._now_iso()
        meta["version"] = int(meta.get("version", 0)) + 1
        updated["meta"] = meta
        self._repo.save(case_id, updated)
        return {
            "meta": {
                "version": meta.get("version"),
                "updated_at": meta.get("updated_at"),
            }
        }

    def save_case_document(self, case_id: str, case_doc: dict) -> None:
        if not self._repo.exists(case_id):
            self._repo.create(case_id, case_doc)
        else:
            self._repo.save(case_id, case_doc)

    def merge_case_document(self, existing: dict, patch: dict) -> dict:
        if existing is None:
            existing = {}
        if not isinstance(existing, dict):
            raise ValueError("Existing case document must be a JSON object")

        if patch is None:
            patch = {}
        if not isinstance(patch, dict):
            raise ValueError("Case update payload must be a JSON object")

        base = copy.deepcopy(existing)
        return self._merge_case_payload(base, patch)

    def _merge_case_payload(self, target: dict, payload: dict) -> dict:
        """Merge close/update payload into canonical case document.

        - Preserves existing fields not present in payload.
        - Updates scalar fields directly (e.g. case_status, closed_at, summary).
        - Recursively merges nested dicts (e.g. d_states partial updates).
        - Replaces lists/scalars when explicitly provided.
        """
        for key, value in payload.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                target[key] = self._merge_case_payload(target[key], value)
                continue
            target[key] = copy.deepcopy(value)
        return target

    def upsert_case_document(self, case_id: str, case_doc: dict) -> None:
        self._repo.save(case_id, case_doc)

    def _now_iso(self) -> str:
        return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    def _validate_patch(self, existing: dict, patch: dict, path: str = "") -> None:
        if not isinstance(patch, dict):
            raise ValueError("PATCH payload must be a JSON object")

        for key, value in patch.items():
            if key not in existing:
                if not self._is_allowed_new_key(path, key):
                    raise ValueError(f"Invalid path: {self._join_path(path, key)}")
                if value is None:
                    continue
                if isinstance(value, dict):
                    self._validate_patch({}, value, self._join_path(path, key))
                continue

            current = existing[key]

            if value is None:
                continue

            if isinstance(current, dict):
                if not isinstance(value, dict):
                    raise ValueError(f"Invalid type at {self._join_path(path, key)}")
                self._validate_patch(current, value, self._join_path(path, key))
                continue

            if isinstance(current, list):
                if not isinstance(value, list):
                    raise ValueError(f"Invalid type at {self._join_path(path, key)}")
                continue

            if isinstance(value, (dict, list)):
                raise ValueError(f"Invalid type at {self._join_path(path, key)}")

    def _join_path(self, base: str, key: str) -> str:
        return f"{base}.{key}" if base else key

    def _is_allowed_new_key(self, path: str, key: str) -> bool:
        if path.endswith(".header"):
            return True
        if ".data" in path:
            return True
        if path == "meta":
            return True
        return False

    def _deep_merge(self, target: dict, patch: dict) -> dict:
        for key, value in patch.items():
            if value is None:
                target[key] = None
                continue

            if isinstance(value, dict) and isinstance(target.get(key), dict):
                target[key] = self._deep_merge(target.get(key, {}), value)
                continue

            if isinstance(value, list):
                target[key] = value
                continue

            target[key] = value

        return target


class CaseIngestionService:
    """Orchestrates ingestion of closed cases into search infrastructure."""

    def __init__(
        self,
        search_index: CaseSearchIndex,
        case_repository: CaseReadRepository,
        embedding_client: EmbeddingClient,
        logger: logging.Logger | None = None,
    ) -> None:
        self._search_index = search_index
        self._case_repository = case_repository
        self._embedding_client = embedding_client
        self._logger = logger or logging.getLogger("case_ingestion")

    def ingest_all_closed_cases(self) -> None:
        paths = self._case_repository.list_case_paths()
        for path in paths:
            case_id = self._extract_case_id(path)
            self.ingest_closed_case(case_id)

    def ingest_closed_case(self, case_id: str) -> None:
        path = f"{case_id}/case.json"
        try:
            data = self._case_repository.load_case(path)
            normalized_case = IncidentStateAdapter.to_legacy_case_doc(data)
            case_model = LegacyCaseModel.model_validate(normalized_case)
        except Exception as exc:
            self._log_outcome("FAILED", case_id, f"schema_validation_error: {exc}")
            return

        case_doc = case_model.model_dump()
        searchable_fields = self._build_searchable_fields(case_doc)

        searchable_fields = self._apply_flattened_fallbacks(case_doc, searchable_fields)

        bm25_text = self._build_embedding_input(searchable_fields)

        if not bm25_text:
            bm25_text = self._build_flattened_embedding_text(case_doc)

        is_closed_case = self._validate_closed_case(case_model)
        if not is_closed_case:
            self._log_outcome("SKIPPED", case_id, "status_not_closed")
            return

        doc_id = self._build_doc_id(case_id)
        self._validate_doc_id(doc_id)

        new_hash = self._searchable_hash(searchable_fields)
        existing_hash = self._existing_doc_hash(doc_id)

        if existing_hash is not None:
            if existing_hash == new_hash:
                self._log_outcome("SKIPPED", case_id, "content_hash_unchanged")
                return

            self._log_outcome(
                "FAILED",
                case_id,
                "content_hash_changed_for_closed_case",
            )
            return

        embedding_input = bm25_text
        if not embedding_input:
            self._log_outcome("FAILED", case_id, "empty_embedding_input")
            return

        try:
            embedding = self._embedding_client.generate_embedding(embedding_input)
        except Exception as exc:
            self._log_outcome("FAILED", case_id, f"embedding_failed: {exc}")
            return

        document = self._build_index_document(case_model.model_dump(), doc_id)
        # searchable_hash is used for the hash comparison above but is NOT a
        # field in the Azure Search index schema — remove it before uploading.
        document.pop("searchable_hash", None)
        document["content_vector"] = embedding

        try:
            self._search_index.upload_documents([document])
        except Exception as exc:
            self._log_outcome("FAILED", case_id, f"index_upsert_failed: {exc}")
            return

        self._log_outcome("SUCCESS", case_id)

    def index_open_case(self, case_id: str) -> None:
        """Index (or re-index) an open case so it is immediately searchable.

        Unlike ``ingest_closed_case`` this method does NOT require the case to
        be closed — it is called after CREATE_CASE and UPDATE_CASE so the case
        appears in search results as soon as it is created.  The content_vector
        is populated opportunistically; if embedding generation fails the
        document is still indexed so that filter-based searches (e.g. by
        case_id) work without a vector.
        """
        self._logger.info("[INDEX_OPEN] called for case_id=%s", case_id)
        path = f"{case_id}/case.json"
        try:
            data = self._case_repository.load_case(path)
            self._logger.info(
                "[INDEX_OPEN] loaded blob doc for %s, top-level keys=%s",
                case_id,
                list(data.keys()) if isinstance(data, dict) else type(data).__name__,
            )
            normalized_case = IncidentStateAdapter.to_legacy_case_doc(data)
            case_model = LegacyCaseModel.model_validate(normalized_case)
        except Exception as exc:
            self._logger.exception(
                "[INDEX_OPEN] failed to load/validate case %s: %s", case_id, exc
            )
            raise RuntimeError(
                f"Failed to load/validate case {case_id}: {exc}"
            ) from exc

        doc_id = self._build_doc_id(case_id)
        self._logger.info("[INDEX_OPEN] doc_id=%s", doc_id)
        document = self._build_index_document(case_model.model_dump(), doc_id)

        # _build_index_document appends 'searchable_hash' which is not a field
        # in the Azure Search index schema — remove it before uploading or the
        # entire document upload will be rejected by the service.
        document.pop("searchable_hash", None)

        # Attempt to generate an embedding for richer search; tolerate failure.
        bm25_text = self._build_embedding_input(
            self._build_searchable_fields(case_model.model_dump())
        )
        if not bm25_text:
            bm25_text = self._build_flattened_embedding_text(case_model.model_dump())
        if bm25_text:
            try:
                document["content_vector"] = self._embedding_client.generate_embedding(
                    bm25_text
                )
                self._logger.info("[INDEX_OPEN] embedding generated for %s", case_id)
            except Exception as exc:
                self._logger.warning(
                    "[INDEX_OPEN] embedding skipped for %s (non-fatal): %s",
                    case_id,
                    exc,
                )
        else:
            self._logger.warning(
                "[INDEX_OPEN] no embedding text found for %s — indexed without vector",
                case_id,
            )

        self._logger.info(
            "[INDEX_OPEN] uploading document fields: %s", list(document.keys())
        )
        try:
            results = self._search_index.merge_or_upload_documents([document])
            self._logger.info(
                "[INDEX_OPEN] upload complete for %s — result item count: %d",
                case_id,
                len(results) if results else 0,
            )
            for r in results:
                if not r.succeeded:
                    self._logger.error(
                        "[INDEX] Document REJECTED by Azure Search: "
                        "key=%s status=%s error='%s'",
                        r.key,
                        r.status_code,
                        r.error_message,
                    )
                    raise RuntimeError(
                        f"Azure Search rejected document {r.key}: {r.error_message}"
                    )
                else:
                    self._logger.info("[INDEX] Document accepted: key=%s", r.key)
        except RuntimeError:
            raise
        except Exception as exc:
            self._logger.exception(
                "[INDEX_OPEN] upload FAILED for %s: %s", case_id, exc
            )

    @staticmethod
    def _now_iso() -> str:
        return datetime.utcnow().isoformat() + "Z"

    @staticmethod
    def _to_search_datetime(value: Any) -> str | None:
        if value is None:
            return None

        # String datetime → ensure timezone
        if isinstance(value, str):
            # If already has timezone, keep it
            if value.endswith("Z") or "+" in value[-6:]:
                return value
            # Otherwise assume UTC
            return value + "Z"

        # datetime object → ensure timezone
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.isoformat()

        return None

    def _log_outcome(
        self, status: str, case_id: str, reason: str | None = None
    ) -> None:
        payload = {
            "timestamp": self._now_iso(),
            "case_id": case_id,
            "status": status,
        }
        if reason:
            payload["reason"] = reason
        self._logger.info(json.dumps(payload))

    @staticmethod
    def _extract_case_id(path: str) -> str:
        parts = path.split("/")
        if len(parts) < 2 or parts[-1] != "case.json":
            raise ValueError(f"Invalid case path: {path}")
        return parts[0]

    def _build_doc_id(self, case_id: str) -> str:
        """Build immutable, versioned document IDs based on the injected index name."""
        return f"{case_id}{self._search_index.get_doc_id_suffix()}"

    def _validate_doc_id(self, doc_id: str) -> None:
        suffix = self._search_index.get_doc_id_suffix()
        if not doc_id.endswith(suffix) or len(doc_id) == len(suffix):
            raise ValueError(f"Invalid doc_id format. Expected '{{case_id}}{suffix}'.")

    @staticmethod
    def _safe_get(data: dict, *keys: str, default: Any = "") -> Any:
        cur: Any = data
        for key in keys:
            if not isinstance(cur, dict) or key not in cur:
                return default
            cur = cur[key]
        return cur

    @staticmethod
    def _coerce_list(value: Any) -> list:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        return [value]

    @staticmethod
    def _normalize_string(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        return str(value)

    @staticmethod
    def _normalize_list(value: Any) -> list[str]:
        return [CaseIngestionService._normalize_string(v) for v in (value or [])]

    @staticmethod
    def _normalize_evidence_descriptions(evidence: list[dict]) -> str:
        values = []
        for item in evidence:
            description = item.get("description") if isinstance(item, dict) else ""
            if description:
                values.append(description)
        return "\n".join(values)

    @staticmethod
    def _normalize_evidence_tags(evidence: list[dict]) -> list[str]:
        tags: list[str] = []
        for item in evidence:
            if not isinstance(item, dict):
                continue
            entry = item.get("tags", [])
            if isinstance(entry, list):
                tags.extend([str(v) for v in entry])
            elif entry:
                tags.append(str(entry))
        return tags

    @staticmethod
    def _collect_discipline_completed(phases: dict[str, Any]) -> list[str]:
        completed = []
        for phase_key, phase in phases.items():
            header = phase.get("header", {}) if isinstance(phase, dict) else {}
            if header.get("completed") is True:
                completed.append(phase_key)
        return completed

    def _build_searchable_fields(self, case_doc: dict) -> dict[str, Any]:
        case = case_doc.get("case", {})
        phases = case_doc.get("phases", {})
        evidence = case_doc.get("evidence", [])

        fishbone = self._safe_get(phases, "D5", "data", "fishbone", default={})
        five_whys = self._safe_get(phases, "D5", "data", "five_whys", default={})

        return {
            "doc_id": None,
            "case_id": case.get("case_number"),
            "status": case.get("status"),
            "opening_date": case.get("opening_date"),
            "closure_date": case.get("closure_date"),
            "created_at": self._safe_get(case_doc, "meta", "created_at"),
            "updated_at": self._safe_get(case_doc, "meta", "updated_at"),
            "version": self._safe_get(case_doc, "meta", "version", default=1),
            "organization_country": self._safe_get(
                phases, "D1_D2", "data", "organization", "country"
            ),
            "organization_site": self._safe_get(
                phases, "D1_D2", "data", "organization", "site"
            ),
            "organization_unit": (
                self._safe_get(phases, "D1_D2", "data", "organization", "department")
                or self._safe_get(phases, "D1_D2", "data", "organization", "area")
            ),
            "discipline_completed": self._collect_discipline_completed(phases),
            "problem_description": self._safe_get(
                phases, "D1_D2", "data", "problem_description"
            ),
            "team_members": self._normalize_team_members(
                self._safe_get(phases, "D1_D2", "data", "team_members", default=[])
            ),
            "what_happened": self._safe_get(phases, "D3", "data", "what_happened"),
            "why_problem": self._safe_get(phases, "D3", "data", "why_problem"),
            "when": self._safe_get(phases, "D3", "data", "when"),
            "where": self._safe_get(phases, "D3", "data", "where"),
            "who": self._safe_get(phases, "D3", "data", "who"),
            "how_identified": self._safe_get(phases, "D3", "data", "how_identified"),
            "impact": self._safe_get(phases, "D3", "data", "impact"),
            "immediate_actions_text": self._join_action_texts(
                self._safe_get(phases, "D4", "data", "actions", default=[]),
            ),
            "permanent_actions_text": self._join_action_texts(
                self._safe_get(phases, "D6", "data", "actions", default=[]),
            ),
            "investigation_tasks_text": self._join_action_texts(
                self._safe_get(phases, "D5", "data", "investigation_tasks", default=[]),
            ),
            "factors_text": self._join_action_texts(
                self._safe_get(phases, "D5", "data", "factors", default=[]),
            ),
            "fishbone_text": self._join_action_texts(fishbone.get("items", [])),
            "five_whys_text": self._join_action_texts(five_whys.get("items", [])),
            "evidence_descriptions": self._normalize_evidence_descriptions(evidence),
            "evidence_tags": self._normalize_evidence_tags(evidence),
            "ai_summary": self._safe_get(case_doc, "ai", "summary", default=""),
        }

    def _apply_flattened_fallbacks(self, case_doc: dict, fields: dict) -> dict:
        flattened = self._build_flattened_fields(case_doc)
        for key, value in flattened.items():
            if not fields.get(key):
                fields[key] = value
        return fields

    def _build_flattened_fields(self, case_doc: dict) -> dict[str, Any]:
        phases = case_doc.get("phases", {})
        fishbone = self._safe_get(phases, "D5", "data", "fishbone", default={})
        five_whys = self._safe_get(phases, "D5", "data", "five_whys", default={})

        return {
            "problem_description": self._safe_get(
                phases, "D1_D2", "data", "problem_description"
            ),
            "what_happened": self._safe_get(phases, "D3", "data", "what_happened"),
            "why_problem": self._safe_get(phases, "D3", "data", "why_problem"),
            "immediate_actions_text": self._join_action_texts(
                self._safe_get(phases, "D4", "data", "actions", default=[]),
            ),
            "permanent_actions_text": self._join_action_texts(
                self._safe_get(phases, "D6", "data", "actions", default=[]),
            ),
            "investigation_tasks_text": self._join_action_texts(
                self._safe_get(phases, "D5", "data", "investigation_tasks", default=[]),
            ),
            "factors_text": self._join_action_texts(
                self._safe_get(phases, "D5", "data", "factors", default=[]),
            ),
            "fishbone_text": self._join_action_texts(fishbone.get("items", [])),
            "five_whys_text": self._join_action_texts(five_whys.get("items", [])),
        }

    def _build_embedding_input(self, fields: dict) -> str:
        parts = []
        for key, value in fields.items():
            if not value:
                continue
            if isinstance(value, list):
                value = ", ".join([str(v) for v in value])
            parts.append(f"{key}: {value}")
        return "\n".join(parts)

    def _build_flattened_embedding_text(self, case_doc: dict) -> str:
        phases = case_doc.get("phases", {})
        pieces = []
        problem = self._safe_get(phases, "D1_D2", "data", "problem_description")
        if problem:
            pieces.append(problem)
        d3_text = self._build_d3_labeled_text(phases)
        if d3_text:
            pieces.append(d3_text)
        for key in ("D4", "D6", "D5"):
            items = self._safe_get(phases, key, "data", "actions", default=[])
            if key == "D5":
                items = self._safe_get(
                    phases, "D5", "data", "investigation_tasks", default=[]
                )
            text = self._join_action_texts(items)
            if text:
                pieces.append(text)
        fishbone = self._safe_get(phases, "D5", "data", "fishbone", default={})
        pieces.append(self._join_action_texts(fishbone.get("items", [])))
        five_whys = self._safe_get(phases, "D5", "data", "five_whys", default={})
        pieces.append(self._join_action_texts(five_whys.get("items", [])))
        return "\n".join([p for p in pieces if p])

    def _build_d3_labeled_text(self, phases: dict[str, Any]) -> str:
        d3 = self._safe_get(phases, "D3", "data", default={})
        if not isinstance(d3, dict):
            return ""
        parts = []
        mapping = {
            "what_happened": "What happened",
            "why_problem": "Why is this a problem",
            "when": "When",
            "where": "Where",
            "who": "Who",
            "how_identified": "How identified",
            "impact": "Impact",
        }
        for key, label in mapping.items():
            value = d3.get(key)
            if value:
                parts.append(f"{label}: {value}")
        return "\n".join(parts)

    @staticmethod
    def _normalize_team_members(value: object) -> list[str]:
        """Coerce team_members to a clean list of strings.

        Accepts:
          - list[str]  → filtered for non-empty strings
          - str        → split on commas and/or newlines
          - None / other → empty list

        Each full name is stored as-is, and individual first/last name
        tokens are also appended so both "Peter Koci" and "Peter", "Koci"
        are independently searchable. Duplicates are removed while
        preserving insertion order.
        """
        if isinstance(value, list):
            names = [str(m).strip() for m in value if str(m).strip()]
        elif isinstance(value, str):
            names = [
                m.strip() for m in value.replace("\n", ",").split(",") if m.strip()
            ]
        else:
            return []

        normalized: list[str] = []
        for name in names:
            normalized.append(name)  # full name: "Peter Koci"
            parts = name.split()
            if len(parts) > 1:
                normalized.extend(parts)  # individual tokens: "Peter", "Koci"

        return list(dict.fromkeys(normalized))  # deduplicate preserving order

    @staticmethod
    def _join_action_texts(items: list[dict]) -> str:
        if not items:
            return ""
        texts = []
        for item in items:
            if isinstance(item, dict):
                text = item.get("action") or item.get("description") or item.get("text")
            else:
                text = str(item)
            if text:
                texts.append(str(text))
        return "\n".join(texts)

    def _validate_closed_case(self, case_doc: LegacyCaseModel) -> bool:
        return case_doc.case.status == "closed"

    def _searchable_hash(self, searchable_fields: dict) -> str:
        payload = json.dumps(searchable_fields, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _existing_doc_hash(self, doc_id: str) -> str | None:
        existing = self._search_index.try_get_document(doc_id)
        if not existing:
            return None
        value = existing.get("searchable_hash")
        if isinstance(value, str):
            return value
        return None

    def _build_index_document(self, case_doc: dict, doc_id: str) -> dict:
        case = case_doc.get("case", {})
        phases = case_doc.get("phases", {})
        evidence = case_doc.get("evidence", [])

        # Primary source: d_states.D1_2.data (blob native structure)
        # Fallback: phases.D1_D2.data (legacy flat model)
        d1_data = (case_doc.get("d_states") or {}).get("D1_2", {}).get("data", {})
        d1_org = d1_data.get("organization") or {}
        d1_d2_data = self._safe_get(phases, "D1_D2", "data") or {}
        d1_d2_org = (
            d1_d2_data.get("organization") if isinstance(d1_d2_data, dict) else {}
        )
        d1_d2_org = d1_d2_org or {}

        def _d1_field(*keys):
            """Walk d1_data keys in order, return first truthy value."""
            for key in keys:
                val = d1_data.get(key)
                if val:
                    return val
            return None

        document = {
            "doc_id": doc_id,
            "case_id": case.get("case_number"),
            "status": case.get("status"),
            "opening_date": self._to_search_datetime(case.get("opening_date")),
            "closure_date": self._to_search_datetime(
                case.get("closure_date")
                or self._safe_get(phases, "D8", "data", "closure_date", default=None)
            ),
            "current_stage": self._determine_current_stage(
                phases, case_doc.get("d_states") or {}, case
            ),
            "created_at": self._to_search_datetime(
                self._safe_get(case_doc, "meta", "created_at")
            ),
            "updated_at": self._to_search_datetime(
                self._safe_get(case_doc, "meta", "updated_at")
            ),
            "version": self._safe_get(case_doc, "meta", "version", default=1),
            "organization_country": (
                d1_org.get("country")
                or d1_data.get("country")
                or d1_d2_org.get("country")
                or None
            ),
            "organization_site": (
                d1_org.get("site")
                or d1_data.get("site")
                or d1_d2_org.get("site")
                or None
            ),
            "organization_unit": (
                d1_data.get("organization_unit")
                or d1_org.get("department")
                or d1_org.get("area")
                or d1_data.get("department")
                or d1_data.get("area")
                or d1_d2_org.get("department")
                or d1_d2_org.get("area")
                or None
            ),
            "discipline_completed": self._collect_discipline_completed(phases),
            "problem_description": (
                _d1_field("problem_description")
                or self._safe_get(phases, "D1_D2", "data", "problem_description")
                or None
            ),
            "team_members": self._normalize_team_members(
                d1_data.get("involved_people_teams")
                or d1_data.get("team_members")
                or self._safe_get(
                    phases, "D1_D2", "data", "involved_people_teams", default=[]
                )
                or self._safe_get(phases, "D1_D2", "data", "team_members", default=[])
                or []
            ),
            "what_happened": self._safe_get(phases, "D3", "data", "what_happened"),
            "why_problem": self._safe_get(phases, "D3", "data", "why_problem"),
            "when": self._safe_get(phases, "D3", "data", "when"),
            "where": self._safe_get(phases, "D3", "data", "where"),
            "who": self._safe_get(phases, "D3", "data", "who"),
            "how_identified": self._safe_get(phases, "D3", "data", "how_identified"),
            "impact": self._safe_get(phases, "D3", "data", "impact"),
            "immediate_actions_text": self._join_action_texts(
                self._safe_get(phases, "D4", "data", "actions", default=[]),
            ),
            "permanent_actions_text": self._join_action_texts(
                self._safe_get(phases, "D6", "data", "actions", default=[]),
            ),
            "investigation_tasks_text": self._join_action_texts(
                self._safe_get(phases, "D5", "data", "investigation_tasks", default=[]),
            ),
            "factors_text": self._join_action_texts(
                self._safe_get(phases, "D5", "data", "factors", default=[]),
            ),
            "fishbone_text": self._join_action_texts(
                self._safe_get(phases, "D5", "data", "fishbone", default={}).get(
                    "items", []
                )
            ),
            "five_whys_text": self._join_action_texts(
                self._safe_get(phases, "D5", "data", "five_whys", default={}).get(
                    "items", []
                )
            ),
            "evidence_descriptions": self._normalize_evidence_descriptions(evidence),
            "evidence_tags": self._normalize_evidence_tags(evidence),
            "ai_summary": self._safe_get(case_doc, "ai", "summary", default=""),
        }
        document["searchable_hash"] = self._searchable_hash(document)
        return document

    _D_STAGE_ORDER: list[str] = [
        "D1_D2",
        "D3",
        "D4",
        "D5",
        "D6",
        "D7",
        "D8",
    ]
    # Maps canonical phase keys (as stored in the index) to user-facing labels.
    _D_STAGE_LABELS: dict[str, str] = {
        "D1_D2": "Problem Definition",
        "D1_2": "Problem Definition",
        "D3": "Containment Actions",
        "D4": "Root Cause Analysis",
        "D5": "Permanent Corrective Actions",
        "D6": "Implementation & Validation",
        "D7": "Prevention",
        "D8": "Closure & Learnings",
    }

    def _determine_current_stage(
        self,
        phases: dict,
        d_states: dict,
        case: dict,
    ) -> str | None:
        """Return the plain-language label of the active D-stage.

        Logic:
        - Closed cases → 'Closure & Learnings' (D8).
        - Otherwise walk the phase order (D1_D2 … D8) and return the label
          of the first phase whose ``header.completed`` is not True.
        - Falls back to None if no phases are present.
        """
        if case.get("status") == "closed":
            return "Closure & Learnings"

        # Try legacy phases structure first.
        if phases:
            for phase_key in self._D_STAGE_ORDER:
                phase = phases.get(phase_key)
                if isinstance(phase, dict):
                    header = phase.get("header") or {}
                    if not header.get("completed"):
                        return self._D_STAGE_LABELS.get(phase_key, phase_key)
            # All phases completed — treat as Closure.
            return "Closure & Learnings"

        # Try native d_states structure (D1_2, D3, …).
        native_order = ["D1_2", "D3", "D4", "D5", "D6", "D7", "D8"]
        if d_states:
            for stage_key in native_order:
                stage = d_states.get(stage_key)
                if isinstance(stage, dict):
                    header = stage.get("header") or {}
                    if not header.get("completed"):
                        return self._D_STAGE_LABELS.get(stage_key, stage_key)
            return "Closure & Learnings"

        return None


__all__ = ["CaseEntryService", "CaseIngestionService", "CaseSearchIndex"]
