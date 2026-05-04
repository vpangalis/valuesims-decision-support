"""
seed_rich_cases.py — Re-seed 3 handcrafted rich cases into blob storage.

Reads CASE_1, CASE_2, CASE_3 from scripts/seed_sample_cases.py and writes them
under the d_states / D1_2 envelope shape produced by scripts/seed_50_cases.py,
but with the rich per-phase data structures that the API and UI expect today.

Cases written (overwrite=True via CaseRepository.save):
    TRM-20250310-0001  closed  Pantograph carbon strip wear  (Saint-Denis)
    TRM-20250518-0002  closed  Bogie axle bearing overheating  (Brussels Anderlecht)
    TRM-20260115-0003  open    Door obstruction sensor false positives  (Rotterdam)

Run from project root:
    python -m scripts.seed_rich_cases
"""

from __future__ import annotations

import ast
import logging
import os
import sys

from dotenv import load_dotenv

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

load_dotenv(override=True)

from backend.core.config import settings
from backend.storage.blob_storage import (
    BlobStorageClient,
    CaseRepository,
    CaseReadRepository,
)
from backend.storage.ingestion.case_ingestion import (
    CaseIngestionService,
    CaseSearchIndex,
)


# scripts/seed_sample_cases.py has a stale top-level import
# (`from backend.knowledge.embeddings import EmbeddingClient`) which fails to
# resolve in the current codebase, so we cannot `import` it. The CASE_1/2/3
# constants in that file are pure data literals (strings, dicts, lists, bools,
# None), so we extract them with ast.literal_eval — no execution, no imports.
def _load_rich_cases() -> tuple[dict, dict, dict]:
    src_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "seed_sample_cases.py"
    )
    with open(src_path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=src_path)

    wanted = {"CASE_1", "CASE_2", "CASE_3"}
    found: dict[str, dict] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        name = node.targets[0].id
        if name in wanted:
            found[name] = ast.literal_eval(node.value)

    missing = wanted - set(found)
    if missing:
        raise RuntimeError(
            f"Could not extract from seed_sample_cases.py: {sorted(missing)}"
        )
    return found["CASE_1"], found["CASE_2"], found["CASE_3"]


CASE_1, CASE_2, CASE_3 = _load_rich_cases()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Phase converters — phases.<X>.data → d_states.<X>.data
# ─────────────────────────────────────────────────────────────────────────────


def _is_completed(src_phase: dict) -> bool:
    return bool((src_phase.get("header") or {}).get("completed"))


def _phase_status(src_phase: dict) -> str:
    return "completed" if _is_completed(src_phase) else "not_started"


def _convert_d1_2(src_phase: dict, case_meta: dict) -> dict:
    src = src_phase.get("data") or {}
    org = src.get("organization") or {}
    team_members = list(src.get("team_members") or [])

    return {
        "status": _phase_status(src_phase),
        "closure_date": None,
        "data": {
            "problem_description": src.get("problem_description", ""),
            "country": org.get("country", ""),
            "site": org.get("site", ""),
            "organization_unit": org.get("department", ""),
            "involved_people_teams": ", ".join(team_members),
            "title": case_meta.get("title", ""),
            "category": case_meta.get("category", ""),
            "organization": dict(org),
            "team_members": team_members,
        },
    }


def _convert_d3(src_phase: dict) -> dict:
    src = src_phase.get("data") or {}
    return {
        "status": _phase_status(src_phase),
        "closure_date": None,
        "data": {
            "what_happened": src.get("what_happened", ""),
            "why_is_problem": src.get("why_problem", ""),
            "when_detected": src.get("when", ""),
            "where_detected": src.get("where", ""),
            "who_detected": src.get("who", ""),
            "how_detected": src.get("how_identified", ""),
            "quantified_impact": src.get("impact", ""),
        },
    }


def _convert_actions_phase(src_phase: dict) -> dict:
    """Used for D4 and D6 — both have the same {actions: [...]} shape."""
    src = src_phase.get("data") or {}
    return {
        "status": _phase_status(src_phase),
        "closure_date": None,
        "data": {"actions": list(src.get("actions") or [])},
    }


def _convert_d5(src_phase: dict) -> dict:
    src = src_phase.get("data") or {}
    fb = src.get("fishbone") or {}
    # Decision B: merge "place" content into "environment_context"; leave material_input empty.
    environment_merged = list(fb.get("environment") or []) + list(fb.get("place") or [])

    return {
        "status": _phase_status(src_phase),
        "closure_date": None,
        "data": {
            "fishbone": {
                "people_organization": list(fb.get("people") or []),
                "process_workflow": list(fb.get("process") or []),
                "tools_systems": list(fb.get("tools") or []),
                "environment_context": environment_merged,
                "policy_management": list(fb.get("management") or []),
                "material_input": [],
            },
            "five_whys": dict(src.get("five_whys") or {}),
            "investigation_tasks": list(src.get("investigation_tasks") or []),
            "factors": list(src.get("factors") or []),
        },
    }


def _convert_d7(src_phase: dict, ai_block: dict) -> dict:
    src = src_phase.get("data") or {}
    recommended = list(ai_block.get("recommended_actions") or [])
    preventive_notes = "\n".join(f"• {a}" for a in recommended) if recommended else ""

    return {
        "status": _phase_status(src_phase),
        "closure_date": None,
        "data": {
            "procedures_updated": bool(src.get("procedures_updated", False)),
            "training_completed": bool(src.get("training_completed", False)),
            "preventive_notes": preventive_notes,
        },
    }


def _convert_d8(src_phase: dict, d1_phase: dict, case_meta: dict) -> dict:
    src = src_phase.get("data") or {}
    quality_approved = bool(src.get("quality_approved", False))
    team_members = list(((d1_phase.get("data") or {}).get("team_members")) or [])
    approver = team_members[0] if (quality_approved and team_members) else ""

    return {
        "status": _phase_status(src_phase),
        "closure_date": None,
        "data": {
            "quality_approved_by": approver,
            "closure_date": src.get("closure_date") or case_meta.get("closure_date"),
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Whole-case converter
# ─────────────────────────────────────────────────────────────────────────────


def build_blob_doc(rich: dict) -> dict:
    """Convert a phases-shape rich case dict to the d_states-shape blob doc."""
    case_meta = rich.get("case") or {}
    phases = rich.get("phases") or {}
    ai_block = rich.get("ai") or {}

    is_closed = str(case_meta.get("status", "")).lower() == "closed"
    d1_phase = phases.get("D1_D2") or {}

    return {
        "case_id": case_meta.get("case_number", ""),
        "case_status": "closed" if is_closed else "open",
        "opened_at": case_meta.get("opening_date"),
        "closed_at": case_meta.get("closure_date") if is_closed else None,
        "d_states": {
            "D1_2": _convert_d1_2(d1_phase, case_meta),
            "D3": _convert_d3(phases.get("D3") or {}),
            "D4": _convert_actions_phase(phases.get("D4") or {}),
            "D5": _convert_d5(phases.get("D5") or {}),
            "D6": _convert_actions_phase(phases.get("D6") or {}),
            "D7": _convert_d7(phases.get("D7") or {}, ai_block),
            "D8": _convert_d8(phases.get("D8") or {}, d1_phase, case_meta),
        },
        "ai": dict(ai_block),
        "meta": dict(rich.get("meta") or {}),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────


def main() -> None:
    blob_client = BlobStorageClient(
        settings.AZURE_STORAGE_CONNECTION_STRING,
        settings.AZURE_STORAGE_CONTAINER,
    )
    case_repo = CaseRepository(blob_client)
    case_read_repo = CaseReadRepository(
        settings.AZURE_STORAGE_CONNECTION_STRING,
        settings.AZURE_STORAGE_CONTAINER,
    )
    search_index = CaseSearchIndex(
        endpoint=settings.AZURE_SEARCH_ENDPOINT,
        index_name=settings.CASE_INDEX_NAME or "case_index_v3",
        admin_key=settings.AZURE_SEARCH_ADMIN_KEY,
    )
    ingestion_service = CaseIngestionService(
        search_index=search_index,
        case_repository=case_read_repo,
        logger=logger,
    )

    uploaded = 0
    indexed = 0
    failed: list[tuple[str, str]] = []

    for rich in (CASE_1, CASE_2, CASE_3):
        case_meta = rich.get("case") or {}
        case_id = (case_meta.get("case_number") or "").strip()
        if not case_id:
            print("SKIP — missing case_number")
            failed.append(("<unknown>", "missing case_number"))
            continue

        is_closed = str(case_meta.get("status", "")).lower() == "closed"

        try:
            blob_doc = build_blob_doc(rich)
            case_repo.save(case_id, blob_doc)
            uploaded += 1
            print(f"BLOB OK   {case_id}")
        except Exception as exc:
            print(f"BLOB FAIL {case_id} — {exc}")
            failed.append((case_id, f"blob_upload: {exc}"))
            continue

        try:
            if is_closed:
                ingestion_service.ingest_closed_case(case_id)
            else:
                ingestion_service.index_open_case(case_id)
            indexed += 1
            print(f"INDEX OK  {case_id}  ({'closed' if is_closed else 'open'})")
        except Exception as exc:
            print(f"INDEX FAIL {case_id} — {exc}")
            failed.append((case_id, f"index: {exc}"))

    print()
    print("=" * 56)
    print(f"Seeded {uploaded}/3 to blob, indexed {indexed}/3 in Azure Search.")
    if failed:
        print(f"Failed ({len(failed)}):")
        for cid, reason in failed:
            print(f"  {cid}: {reason}")
    else:
        print("No failures.")
    print("=" * 56)


if __name__ == "__main__":
    main()
