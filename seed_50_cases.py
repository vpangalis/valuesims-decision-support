"""
seed_50_cases.py — Upload and index 50 railway/tram sample cases from JSON.

Run from project root:
    python seed_50_cases.py
"""

from __future__ import annotations

import json
import logging
import os
import sys

from dotenv import load_dotenv

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

load_dotenv(override=True)

from backend.config import settings
from backend.infra.blob_storage import BlobStorageClient, CaseReadRepository
from backend.infra.embeddings import EmbeddingClient
from backend.ingestion.case_ingestion import CaseIngestionService, CaseSearchIndex

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Source file
# ─────────────────────────────────────────────────────────────────────────────

JSON_PATH = r"C:\Users\mavep\downloads\cosolve_sample_cases_50.json"


# ─────────────────────────────────────────────────────────────────────────────
# Conversion helpers
# ─────────────────────────────────────────────────────────────────────────────


def _as_datetime(date_str: str | None) -> str | None:
    """Ensure date strings like '2023-01-12' carry a UTC time component."""
    if not date_str:
        return None
    date_str = str(date_str).strip()
    if "T" in date_str:
        return (
            date_str
            if (date_str.endswith("Z") or "+" in date_str[-6:])
            else date_str + "Z"
        )
    return date_str + "T00:00:00Z"


def _d_state_block(text: str | None, completed: bool = True) -> dict:
    """Wrap a plain text string as a d_state block understood by IncidentStateAdapter."""
    return {
        "status": "completed" if completed else "not_started",
        "closure_date": None,
        "data": {"description": text or ""},
    }


def build_blob_document(case: dict) -> dict:
    """
    Convert a flat JSON case record into the native blob document format.

    IncidentStateAdapter.to_legacy_case_doc() will later normalise this into
    the LegacyCaseModel (phases.D1_D2, D3 … D8) that the ingestion pipeline
    consumes.
    """
    is_closed = str(case.get("status", "closed")).lower() == "closed"
    d_states_raw = case.get("d_states") or {}

    # D1_2: problem description + org metadata
    d1_text = str(d_states_raw.get("D1_2") or "").strip()
    d1_data: dict = {
        "problem_description": d1_text,
        # Top-level fields also stored here so the adapter can surface them
        # as organization_country / organization_site in the index document.
        "country": case.get("country") or "",
        "site": case.get("site") or "",
        "fleet": case.get("fleet") or "",
        "line": case.get("line") or "",
        "category": case.get("category") or "",
        "title": case.get("title") or "",
    }

    def _phase(text: str | None, data_extra: dict | None = None) -> dict:
        data = {"description": (text or "").strip()}
        if data_extra:
            data.update(data_extra)
        return {
            "status": "completed" if is_closed else "not_started",
            "closure_date": None,
            "data": data,
        }

    return {
        "case_id": case["case_id"],
        "case_status": "closed" if is_closed else "open",
        "opened_at": _as_datetime(case.get("opened_at")),
        "closed_at": _as_datetime(case.get("closed_at")) if is_closed else None,
        "d_states": {
            "D1_2": {
                "status": "completed" if is_closed else "not_started",
                "closure_date": None,
                "data": d1_data,
            },
            "D3": _phase(d_states_raw.get("D3")),
            "D4": _phase(d_states_raw.get("D4")),
            "D5": _phase(d_states_raw.get("D5")),
            "D6": _phase(d_states_raw.get("D6")),
            "D7": _phase(d_states_raw.get("D7")),
            "D8": _phase(d_states_raw.get("D8")),
        },
        "ai": {
            "last_run": None,
            "summary": str(case.get("summary") or ""),
            "identified_root_causes": [],
            "recommended_actions": [],
        },
        "meta": {
            "version": 1,
            "created_at": _as_datetime(case.get("opened_at")),
            "updated_at": _as_datetime(case.get("closed_at") or case.get("opened_at")),
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────


def main() -> None:
    # ----- Validate source file -----
    if not os.path.isfile(JSON_PATH):
        print(f"ERROR: Source file not found: {JSON_PATH}")
        sys.exit(1)

    with open(JSON_PATH, encoding="utf-8") as fh:
        raw_cases: list[dict] = json.load(fh)

    total = len(raw_cases)
    print(f"Loaded {total} cases from {JSON_PATH}")

    # ----- Build Azure clients -----
    blob_client = BlobStorageClient(
        settings.AZURE_STORAGE_CONNECTION_STRING,
        settings.AZURE_STORAGE_CONTAINER,
    )
    case_read_repo = CaseReadRepository(
        settings.AZURE_STORAGE_CONNECTION_STRING,
        settings.AZURE_STORAGE_CONTAINER,
    )
    search_index = CaseSearchIndex(
        endpoint=settings.AZURE_SEARCH_ENDPOINT,
        index_name=settings.CASE_INDEX_NAME or "case_index_v3",
        admin_key=settings.AZURE_SEARCH_ADMIN_KEY,
    )
    embedding_client = EmbeddingClient()
    ingestion_service = CaseIngestionService(
        search_index=search_index,
        case_repository=case_read_repo,
        embedding_client=embedding_client,
        logger=logger,
    )

    # ----- Upload + Index -----
    uploaded = 0
    indexed = 0
    failed: list[tuple[str, str]] = []

    for i, raw in enumerate(raw_cases, start=1):
        case_id = str(raw.get("case_id") or "").strip()
        if not case_id:
            print(f"  [{i}/{total}] SKIP — missing case_id")
            failed.append((f"row_{i}", "missing case_id"))
            continue

        is_closed = str(raw.get("status", "closed")).lower() == "closed"

        try:
            blob_doc = build_blob_document(raw)
            blob_path = f"{case_id}/case.json"
            blob_client.upload_json(
                blob_path, json.dumps(blob_doc, indent=2), overwrite=True
            )
            uploaded += 1
        except Exception as exc:
            msg = f"blob_upload_failed: {exc}"
            print(f"  [{i}/{total}] FAIL  {case_id} — {msg}")
            failed.append((case_id, msg))
            continue

        try:
            if is_closed:
                ingestion_service.ingest_closed_case(case_id)
            else:
                ingestion_service.index_open_case(case_id)
            indexed += 1
        except Exception as exc:
            msg = f"index_failed: {exc}"
            print(f"  [{i}/{total}] FAIL  {case_id} — {msg}")
            failed.append((case_id, msg))
            continue

        print(f"  [{i}/{total}] OK    {case_id}  ({'closed' if is_closed else 'open'})")

    # ----- Summary -----
    print()
    print("=" * 56)
    print(
        f"Seeding complete: {uploaded}/{total} uploaded to blob, {indexed}/{total} indexed"
    )
    if failed:
        print(f"Failed ({len(failed)}):")
        for cid, reason in failed:
            print(f"  {cid}: {reason}")
    else:
        print("No failures.")
    print("=" * 56)


if __name__ == "__main__":
    main()
