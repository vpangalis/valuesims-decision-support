"""
rebuild_index.py — Deletes and recreates case_index_v3 with corrected schema.

Changes vs previous schema:
  - organization_department  →  organization_unit  (renamed)
  - organization_country, organization_site, organization_unit  →  now SearchableField
    (previously only filterable; now both filterable AND searchable for full-text queries)

Run once from project root:
    python -m scripts.rebuild_index
"""

from __future__ import annotations

import logging
import os
import sys

from dotenv import load_dotenv

# ── make sure project root is on sys.path when run as a module ──────────────
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

load_dotenv(override=True)

from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import ResourceNotFoundError
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    HnswAlgorithmConfiguration,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SearchableField,
    SimpleField,
    VectorSearch,
    VectorSearchProfile,
)

from backend.core.config import settings
from backend.storage.blob_storage import CaseReadRepository
from backend.storage.ingestion.case_ingestion import CaseIngestionService, CaseSearchIndex

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

INDEX_NAME = settings.CASE_INDEX_NAME or "case_index_v3"
VECTOR_PROFILE = "case-vector-profile"
VECTOR_ALGO = "case-hnsw"
EMBEDDING_DIM = 3072  # text-embedding-3-large


# ─────────────────────────────────────────────────────────────────────────────
# Schema
# ─────────────────────────────────────────────────────────────────────────────


def build_index_schema() -> SearchIndex:
    """Corrected case_index_v3 schema with organization_unit."""

    # Collection helper
    Coll = SearchFieldDataType.Collection

    fields = [
        # ── Key ──────────────────────────────────────────────────────────────
        SimpleField(
            name="doc_id",
            type=SearchFieldDataType.String,
            key=True,
            filterable=True,
        ),
        # ── Case identity ─────────────────────────────────────────────────────
        SearchableField(
            name="case_id",
            type=SearchFieldDataType.String,
            filterable=True,
            sortable=True,
            analyzer_name="standard",
        ),
        SimpleField(
            name="status",
            type=SearchFieldDataType.String,
            filterable=True,
            sortable=True,
        ),
        SimpleField(
            name="current_stage",
            type=SearchFieldDataType.String,
            filterable=True,
            sortable=False,
        ),
        SimpleField(
            name="opening_date",
            type=SearchFieldDataType.DateTimeOffset,
            filterable=True,
            sortable=True,
        ),
        SimpleField(
            name="closure_date",
            type=SearchFieldDataType.DateTimeOffset,
            filterable=True,
            sortable=True,
        ),
        SimpleField(
            name="created_at",
            type=SearchFieldDataType.DateTimeOffset,
            filterable=True,
            sortable=True,
        ),
        SimpleField(
            name="updated_at",
            type=SearchFieldDataType.DateTimeOffset,
            filterable=True,
            sortable=True,
        ),
        SimpleField(
            name="version",
            type=SearchFieldDataType.Int32,
            filterable=True,
        ),
        # ── Organization — all three searchable AND filterable ────────────────
        SearchableField(
            name="organization_country",
            type=SearchFieldDataType.String,
            filterable=True,
            sortable=True,
        ),
        SearchableField(
            name="organization_site",
            type=SearchFieldDataType.String,
            filterable=True,
            sortable=True,
        ),
        SearchableField(
            name="organization_unit",  # ← renamed from organization_department
            type=SearchFieldDataType.String,
            filterable=True,
            sortable=True,
        ),
        # ── Collections ───────────────────────────────────────────────────────
        SimpleField(
            name="discipline_completed",
            type=Coll(SearchFieldDataType.String),
            filterable=True,
        ),
        SearchField(
            name="team_members",
            type=Coll(SearchFieldDataType.String),
            searchable=True,
            filterable=True,
            analyzer_name="keyword",  # exact token match per item, no stop words/stemming
        ),
        SimpleField(
            name="evidence_tags",
            type=Coll(SearchFieldDataType.String),
            filterable=True,
        ),
        # ── Searchable text fields ────────────────────────────────────────────
        SearchableField(name="problem_description", type=SearchFieldDataType.String),
        SearchableField(name="what_happened", type=SearchFieldDataType.String),
        SearchableField(name="why_problem", type=SearchFieldDataType.String),
        SearchableField(name="when", type=SearchFieldDataType.String),
        SearchableField(name="where", type=SearchFieldDataType.String),
        SearchableField(name="who", type=SearchFieldDataType.String),
        SearchableField(name="how_identified", type=SearchFieldDataType.String),
        SearchableField(name="impact", type=SearchFieldDataType.String),
        SearchableField(name="immediate_actions_text", type=SearchFieldDataType.String),
        SearchableField(name="permanent_actions_text", type=SearchFieldDataType.String),
        SearchableField(
            name="investigation_tasks_text", type=SearchFieldDataType.String
        ),
        SearchableField(name="factors_text", type=SearchFieldDataType.String),
        SearchableField(name="fishbone_text", type=SearchFieldDataType.String),
        SearchableField(name="five_whys_text", type=SearchFieldDataType.String),
        SearchableField(name="evidence_descriptions", type=SearchFieldDataType.String),
        SearchableField(name="ai_summary", type=SearchFieldDataType.String),
        # ── Rich text for LangChain VectorStore ─────────────────────────────
        SearchableField(name="content_text", type=SearchFieldDataType.String),
        # ── Vector ────────────────────────────────────────────────────────────
        SearchField(
            name="embedding",
            type=Coll(SearchFieldDataType.Single),
            searchable=True,
            vector_search_dimensions=EMBEDDING_DIM,
            vector_search_profile_name=VECTOR_PROFILE,
        ),
    ]

    vector_search = VectorSearch(
        algorithms=[HnswAlgorithmConfiguration(name=VECTOR_ALGO)],
        profiles=[
            VectorSearchProfile(
                name=VECTOR_PROFILE,
                algorithm_configuration_name=VECTOR_ALGO,
            )
        ],
    )

    return SearchIndex(name=INDEX_NAME, fields=fields, vector_search=vector_search)


# ─────────────────────────────────────────────────────────────────────────────
# Rebuild
# ─────────────────────────────────────────────────────────────────────────────


def rebuild() -> None:
    credential = AzureKeyCredential(settings.AZURE_SEARCH_ADMIN_KEY)
    index_client = SearchIndexClient(
        endpoint=settings.AZURE_SEARCH_ENDPOINT,
        credential=credential,
    )

    # ── Step 1: delete existing index ────────────────────────────────────────
    try:
        index_client.delete_index(INDEX_NAME)
        logger.info("Deleted existing index: %s", INDEX_NAME)
    except ResourceNotFoundError:
        logger.info("Index %s did not exist — nothing to delete.", INDEX_NAME)
    except Exception as exc:
        logger.warning("Could not delete index (non-fatal): %s", exc)

    # ── Step 2: create new index ──────────────────────────────────────────────
    schema = build_index_schema()
    index_client.create_index(schema)
    logger.info("Created new index: %s", INDEX_NAME)

    # ── Step 3: re-index all cases from blob ─────────────────────────────────
    case_read_repo = CaseReadRepository(
        connection_string=settings.AZURE_STORAGE_CONNECTION_STRING,
        container_name=settings.AZURE_STORAGE_CONTAINER,
    )
    search_index = CaseSearchIndex(
        endpoint=settings.AZURE_SEARCH_ENDPOINT,
        index_name=INDEX_NAME,
        admin_key=settings.AZURE_SEARCH_ADMIN_KEY,
    )
    case_ingestion = CaseIngestionService(
        search_index=search_index,
        case_repository=case_read_repo,
    )

    paths = case_read_repo.list_case_paths()
    case_ids = [p.replace("/case.json", "") for p in paths]
    logger.info("Found %d case(s) to re-index: %s", len(case_ids), case_ids)

    success = 0
    failed = 0
    for case_id in case_ids:
        try:
            case_ingestion.index_open_case(case_id)
            logger.info("  ✓ Indexed %s", case_id)
            success += 1
        except Exception as exc:
            logger.error("  ✗ Failed %s: %s", case_id, exc)
            failed += 1

    logger.info("Done. Success: %d  Failed: %d", success, failed)


if __name__ == "__main__":
    rebuild()
