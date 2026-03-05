"""
backfill_confirmed_at.py — One-off: stamp confirmed_at on completed phases
for cases that were confirmed before the field was introduced.

Strategy:
  - For each case, collect all phases with status="completed" in phase order.
  - Distribute confirmed_at timestamps evenly between opened_at and
    closed_at (closed cases) or today (open cases).
  - Skips any phase that already has a confirmed_at value.
  - Dry-run by default — pass --write to persist changes.

Run from project root:
    python -m scripts.backfill_confirmed_at           # dry-run
    python -m scripts.backfill_confirmed_at --write   # persist to blob
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(override=True)

from backend.config import settings
from backend.infra.blob_storage import BlobStorageClient, CaseRepository

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

PHASE_ORDER = ["D1_2", "D3", "D4", "D5", "D6", "D7", "D8"]


def parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        # Handle both date-only and full ISO strings
        if "T" in s:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def iso_date(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def backfill_case(case: dict) -> tuple[dict, bool]:
    """Return (updated_case, was_changed)."""
    opened_at = parse_iso(case.get("opened_at"))
    closed_at  = parse_iso(case.get("closed_at"))
    end_dt     = closed_at or datetime.now(tz=timezone.utc)

    if not opened_at:
        logger.warning("  Skipping — no opened_at")
        return case, False

    d_states = case.get("d_states", {})

    # Collect completed phases that need a confirmed_at, in order
    needs_stamp = [
        p for p in PHASE_ORDER
        if d_states.get(p, {}).get("status") == "completed"
        and not d_states.get(p, {}).get("confirmed_at")
    ]

    if not needs_stamp:
        return case, False

    # Distribute evenly: divide the total span into (n+1) equal slices so
    # the last confirmed_at lands at ~90% of the span (leaves a small tail).
    total_span = (end_dt - opened_at).total_seconds()
    n = len(needs_stamp)
    changed = False

    for i, phase in enumerate(needs_stamp):
        fraction = (i + 1) / (n + 1)
        confirmed_dt = opened_at + timedelta(seconds=total_span * fraction)
        stamp = iso_date(confirmed_dt)
        d_states.setdefault(phase, {})["confirmed_at"] = stamp
        logger.info("    %-6s  confirmed_at = %s", phase, stamp)
        changed = True

    case["d_states"] = d_states
    return case, changed


def run(write: bool) -> None:
    blob = BlobStorageClient(
        settings.AZURE_STORAGE_CONNECTION_STRING,
        settings.AZURE_STORAGE_CONTAINER,
    )
    repo = CaseRepository(blob)

    # List all case.json blobs
    all_blobs = blob.list_files("")
    case_paths = [b["name"] for b in all_blobs if b["name"].endswith("/case.json")]
    logger.info("Found %d case(s) in blob storage", len(case_paths))

    patched = 0
    for path in sorted(case_paths):
        case_id = path.split("/")[0]
        logger.info("Processing %s ...", case_id)
        try:
            case_doc = repo.load(case_id)
        except Exception as exc:
            logger.error("  Could not load %s: %s", case_id, exc)
            continue

        updated, changed = backfill_case(case_doc)
        if not changed:
            logger.info("  No changes needed.")
            continue

        if write:
            try:
                repo.save(case_id, updated)
                logger.info("  Saved.")
                patched += 1
            except Exception as exc:
                logger.error("  Save failed: %s", exc)
        else:
            logger.info("  (dry-run — not saved)")
            patched += 1

    mode = "patched" if write else "would patch"
    logger.info("Done. %d case(s) %s.", patched, mode)
    if not write:
        logger.info("Re-run with --write to persist changes.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill confirmed_at on completed phases.")
    parser.add_argument("--write", action="store_true", help="Persist changes to blob (default: dry-run)")
    args = parser.parse_args()
    run(write=args.write)
