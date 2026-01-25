from __future__ import annotations

from typing import Iterable
import os
import re

from azure.core.credentials import AzureKeyCredential
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

from app.config import settings

CASE_INDEX_NAME = "case_index_v3"
VECTOR_ALGORITHM_NAME = "case_hnsw_v1"
VECTOR_PROFILE_NAME = "case_vector_profile_v1"
DOC_ID_SUFFIX = f"__{CASE_INDEX_NAME}"
DOC_ID_PATTERN = re.compile(rf"^.+{re.escape(DOC_ID_SUFFIX)}$")


def _collection_string() -> SearchFieldDataType:
    return SearchFieldDataType.Collection(SearchFieldDataType.String)


def _collection_float() -> SearchFieldDataType:
    return SearchFieldDataType.Collection(SearchFieldDataType.Single)


def build_doc_id(case_id: str) -> str:
    """Build immutable, versioned document IDs for case_index_v3."""
    return f"{case_id}{DOC_ID_SUFFIX}"


def validate_doc_id(doc_id: str) -> None:
    """Fail fast if a doc_id does not match {case_id}::case_index_v3."""
    if not DOC_ID_PATTERN.match(doc_id):
        raise ValueError("Invalid doc_id format. Expected '{case_id}__case_index_v3'.")


def _case_index_fields(vector_dimensions: int) -> Iterable[SearchField]:
    return [
        SimpleField(
            name="doc_id",
            type=SearchFieldDataType.String,
            key=True,
            filterable=True,
            sortable=True,
        ),
        SimpleField(
            name="case_id",
            type=SearchFieldDataType.String,
            filterable=True,
            sortable=True,
        ),
        SimpleField(
            name="status",
            type=SearchFieldDataType.String,
            filterable=True,
            facetable=True,
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
            sortable=True,
        ),
        SimpleField(
            name="organization_country",
            type=SearchFieldDataType.String,
            filterable=True,
            facetable=True,
            sortable=True,
        ),
        SimpleField(
            name="organization_site",
            type=SearchFieldDataType.String,
            filterable=True,
            facetable=True,
            sortable=True,
        ),
        SimpleField(
            name="organization_department",
            type=SearchFieldDataType.String,
            filterable=True,
            facetable=True,
            sortable=True,
        ),
        SearchField(
            name="discipline_completed",
            type=_collection_string(),
            filterable=True,
            facetable=True,
        ),
        SearchableField(
            name="problem_description",
            type=SearchFieldDataType.String,
        ),
        SearchField(
            name="team_members",
            type=_collection_string(),
            searchable=True,
            filterable=False,
            facetable=False,
        ),
        SearchableField(
            name="what_happened",
            type=SearchFieldDataType.String,
        ),
        SearchableField(
            name="why_problem",
            type=SearchFieldDataType.String,
        ),
        SearchableField(
            name="when",
            type=SearchFieldDataType.String,
        ),
        SearchableField(
            name="where",
            type=SearchFieldDataType.String,
        ),
        SearchableField(
            name="who",
            type=SearchFieldDataType.String,
        ),
        SearchableField(
            name="how_identified",
            type=SearchFieldDataType.String,
        ),
        SearchableField(
            name="impact",
            type=SearchFieldDataType.String,
        ),
        SearchableField(
            name="immediate_actions_text",
            type=SearchFieldDataType.String,
        ),
        SearchableField(
            name="permanent_actions_text",
            type=SearchFieldDataType.String,
        ),
        SearchableField(
            name="investigation_tasks_text",
            type=SearchFieldDataType.String,
        ),
        SearchableField(
            name="factors_text",
            type=SearchFieldDataType.String,
        ),
        SearchableField(
            name="fishbone_text",
            type=SearchFieldDataType.String,
        ),
        SearchableField(
            name="five_whys_text",
            type=SearchFieldDataType.String,
        ),
        SearchableField(
            name="evidence_descriptions",
            type=SearchFieldDataType.String,
        ),
        SearchField(
            name="evidence_tags",
            type=_collection_string(),
            searchable=True,
            filterable=False,
            facetable=False,
        ),
        SearchableField(
            name="ai_summary",
            type=SearchFieldDataType.String,
        ),
        SearchField(
            name="content_vector",
            type=_collection_float(),
            searchable=True,
            vector_search_dimensions=vector_dimensions,
            vector_search_profile_name=VECTOR_PROFILE_NAME,
        ),
    ]


def build_case_index(index_name: str, vector_dimensions: int) -> SearchIndex:
    # Schema changes require a new index version (e.g., case_index_v3).
    if index_name != CASE_INDEX_NAME:
        raise ValueError(
            "Index name override is not allowed for Sprint 3. "
            "Use case_index_v3 for schema changes."
        )
    vector_search = VectorSearch(
        algorithms=[
            HnswAlgorithmConfiguration(
                name=VECTOR_ALGORITHM_NAME,
            )
        ],
        profiles=[
            VectorSearchProfile(
                name=VECTOR_PROFILE_NAME,
                algorithm_configuration_name=VECTOR_ALGORITHM_NAME,
            )
        ],
    )

    return SearchIndex(
        name=index_name,
        fields=list(_case_index_fields(vector_dimensions)),
        vector_search=vector_search,
    )


def create_or_update_case_index(
    endpoint: str | None = None,
    admin_key: str | None = None,
    vector_dimensions: int | None = None,
) -> SearchIndex:
    resolved_endpoint = endpoint or settings.AZURE_SEARCH_ENDPOINT
    resolved_admin_key = admin_key or settings.AZURE_SEARCH_ADMIN_KEY
    resolved_vector_dimensions = (
        vector_dimensions or settings.AZURE_SEARCH_VECTOR_DIMENSIONS
    )

    # Prevent environment overrides of the index name for Sprint 3.
    if os.getenv("AZURE_SEARCH_INDEX_NAME"):
        raise ValueError(
            "AZURE_SEARCH_INDEX_NAME overrides are not allowed for Sprint 3. "
            "case_index_v3 is immutable; use case_index_v3 for schema changes."
        )

    client = SearchIndexClient(
        endpoint=resolved_endpoint,
        credential=AzureKeyCredential(resolved_admin_key),
    )

    index = build_case_index(
        index_name=CASE_INDEX_NAME,
        vector_dimensions=resolved_vector_dimensions,
    )

    return client.create_or_update_index(index)


if __name__ == "__main__":
    create_or_update_case_index()
