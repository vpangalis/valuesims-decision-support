"""
patch_country_vienna.py — One-off: fix country/site for two docs where
country was incorrectly stored as 'vienna' (lowercase).

Applies a merge-only update (does NOT touch any other indexed fields).

Target documents:
    INC-20260126-0003  →  country="Austria", site="Vienna"
    INC-20260122-0001  →  country="Austria", site="Vienna"

Run from project root:
    python -m scripts.patch_country_vienna
"""

from __future__ import annotations

import logging
import os
import sys

from dotenv import load_dotenv

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

load_dotenv(override=True)

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient

from backend.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


INDEX_NAME = settings.CASE_INDEX_NAME or "case_index_v3"

# doc_id  →  (new_country, new_site)
PATCHES: dict[str, tuple[str, str]] = {
    "INC-20260126-0003__case_index_v3": ("Austria", "Vienna"),
    "INC-20260122-0001__case_index_v3": ("Austria", "Vienna"),
}


def run() -> None:
    client = SearchClient(
        endpoint=settings.AZURE_SEARCH_ENDPOINT,
        index_name=INDEX_NAME,
        credential=AzureKeyCredential(settings.AZURE_SEARCH_ADMIN_KEY),
    )

    # ── Verify both documents exist before patching ───────────────────────────
    logger.info("Verifying documents exist in index '%s' ...", INDEX_NAME)
    for doc_id in PATCHES:
        try:
            existing = client.get_document(key=doc_id, selected_fields=["doc_id", "organization_country", "organization_site"])
            logger.info(
                "  FOUND  doc_id=%-45s  country=%r  site=%r",
                doc_id,
                existing.get("organization_country"),
                existing.get("organization_site"),
            )
        except Exception as exc:
            logger.error("  NOT FOUND  doc_id=%s  error=%s", doc_id, exc)
            raise SystemExit(1)

    # ── Build merge payloads ──────────────────────────────────────────────────
    merge_docs = [
        {
            "doc_id": doc_id,
            "organization_country": country,
            "organization_site": site,
        }
        for doc_id, (country, site) in PATCHES.items()
    ]

    # ── Merge (only the specified fields are updated) ─────────────────────────
    logger.info("Applying merge patch to %d document(s) ...", len(merge_docs))
    results = client.merge_documents(documents=merge_docs)

    all_ok = True
    for result in results:
        if result.succeeded:
            logger.info("  OK  doc_id=%-45s  key=%s", result.key, result.key)
        else:
            logger.error(
                "  FAILED  doc_id=%-45s  status=%s  error=%s",
                result.key,
                result.status_code,
                result.error_message,
            )
            all_ok = False

    if not all_ok:
        raise SystemExit("One or more documents failed to update.")

    # ── Confirm final state ───────────────────────────────────────────────────
    logger.info("Confirming final state ...")
    for doc_id in PATCHES:
        doc = client.get_document(key=doc_id, selected_fields=["doc_id", "organization_country", "organization_site"])
        logger.info(
            "  CONFIRMED  doc_id=%-45s  country=%r  site=%r",
            doc_id,
            doc.get("organization_country"),
            doc.get("organization_site"),
        )

    logger.info("Done. %d document(s) patched successfully.", len(PATCHES))


if __name__ == "__main__":
    run()
