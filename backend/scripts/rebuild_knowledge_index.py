"""
rebuild_knowledge_index.py — Creates (or updates) knowledge_index_v2 with the
hierarchical chunking schema.

New fields vs knowledge_index_v1:
  chunk_type         — document_summary | section | small_chunk
  section_title      — heading text for section / small_chunk entries
  parent_section_id  — doc_id of the parent section for small_chunk entries
  page_start         — first page number covered by this chunk (0 = unknown)
  page_end           — last page number covered by this chunk (0 = unknown)
  cosolve_phase      — diagnose | root_cause | correct | prevent | general
  char_count         — character count of content_text

Run once from project root:
    python -m backend.scripts.rebuild_knowledge_index
"""

from __future__ import annotations

import logging
import os
import sys

from dotenv import load_dotenv

# ── make sure project root is on sys.path when run as a module ──────────────
_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

load_dotenv(override=True)

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
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

from backend.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

INDEX_NAME = "knowledge_index_v2"
VECTOR_PROFILE = "knowledge-vector-profile"
VECTOR_ALGO = "knowledge-hnsw"
EMBEDDING_DIM = 3072  # text-embedding-3-large


class KnowledgeIndexBuilder:
    """Creates or updates knowledge_index_v2 with the hierarchical chunking schema."""

    def __init__(self) -> None:
        self._credential = AzureKeyCredential(settings.AZURE_SEARCH_ADMIN_KEY)
        self._index_client = SearchIndexClient(
            endpoint=settings.AZURE_SEARCH_ENDPOINT,
            credential=self._credential,
        )

    def build_index(self) -> None:
        print(f"[knowledge_index] target index: {INDEX_NAME}")
        logger.info("Target index: %s", INDEX_NAME)

        # ── Collection helper ─────────────────────────────────────────────────
        Coll = SearchFieldDataType.Collection

        fields = [
            # ── Key ───────────────────────────────────────────────────────────
            SimpleField(
                name="doc_id",
                type=SearchFieldDataType.String,
                key=True,
            ),
            # ── v1 fields (backward-compatible) ───────────────────────────────
            SearchableField(
                name="doc_type",
                type=SearchFieldDataType.String,
                filterable=True,
            ),
            SearchableField(
                name="title",
                type=SearchFieldDataType.String,
                filterable=True,
            ),
            SearchableField(
                name="content_text",
                type=SearchFieldDataType.String,
            ),
            SearchableField(
                name="source",
                type=SearchFieldDataType.String,
                filterable=True,
            ),
            SimpleField(
                name="version",
                type=SearchFieldDataType.String,
                filterable=True,
            ),
            SimpleField(
                name="created_at",
                type=SearchFieldDataType.DateTimeOffset,
                filterable=True,
            ),
            # ── New hierarchical chunking fields ───────────────────────────────
            SearchableField(
                name="chunk_type",
                type=SearchFieldDataType.String,
                filterable=True,
            ),
            SearchableField(
                name="section_title",
                type=SearchFieldDataType.String,
            ),
            SimpleField(
                name="parent_section_id",
                type=SearchFieldDataType.String,
                filterable=True,
            ),
            SimpleField(
                name="page_start",
                type=SearchFieldDataType.Int32,
                filterable=True,
            ),
            SimpleField(
                name="page_end",
                type=SearchFieldDataType.Int32,
                filterable=True,
            ),
            SearchableField(
                name="cosolve_phase",
                type=SearchFieldDataType.String,
                filterable=True,
            ),
            SimpleField(
                name="char_count",
                type=SearchFieldDataType.Int32,
                filterable=True,
            ),
            # ── Vector ────────────────────────────────────────────────────────
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

        schema = SearchIndex(
            name=INDEX_NAME, fields=fields, vector_search=vector_search
        )
        self._index_client.create_or_update_index(schema)
        logger.info("Created / updated index: %s", INDEX_NAME)

        search_client = SearchClient(
            endpoint=settings.AZURE_SEARCH_ENDPOINT,
            index_name=INDEX_NAME,
            credential=self._credential,
        )
        doc_count = search_client.get_document_count()
        print(
            f"[knowledge_index] SUCCESS — index '{INDEX_NAME}' ready. "
            f"Document count: {doc_count}"
        )
        logger.info("Index '%s' is ready. Document count: %d", INDEX_NAME, doc_count)


if __name__ == "__main__":
    KnowledgeIndexBuilder().build_index()
