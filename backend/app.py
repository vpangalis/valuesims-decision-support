from __future__ import annotations

from dotenv import load_dotenv
load_dotenv(override=True)

import logging
import os

from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import ResourceNotFoundError
from azure.search.documents.indexes import SearchIndexClient
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import settings
from backend.api import routes
from backend.api.support_routes import build_support_router
from backend.entry.entry_handler import EntryHandler
from backend.graph import compiled_graph
from backend.infra.blob_storage import BlobStorageClient, CaseRepository, CaseReadRepository
from backend.infra.embeddings import EmbeddingClient
from backend.infra.case_search_client import CaseSearchClient
from backend.infra.evidence_search_client import EvidenceSearchClient
from backend.llm import get_llm
from backend.infra.knowledge_search_client import KnowledgeSearchClient
from backend.ingestion.case_ingestion import CaseEntryService, CaseIngestionService, CaseSearchIndex
from backend.ingestion.evidence_ingestion import EvidenceIngestionService, EvidenceSearchIndex
from backend.ingestion.knowledge_ingestion import KnowledgeIngestionService, KnowledgeSearchIndex
from backend.tools import KPITool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# OTLP tracing setup
# ---------------------------------------------------------------------------
_otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
if _otlp_endpoint:
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry import trace as otel_trace
    _otlp_exporter = OTLPSpanExporter(endpoint=_otlp_endpoint, insecure=True)
    _provider = otel_trace.get_tracer_provider()
    if hasattr(_provider, "add_span_processor"):
        _provider.add_span_processor(BatchSpanProcessor(_otlp_exporter))


# ---------------------------------------------------------------------------
# Infrastructure singletons
# ---------------------------------------------------------------------------
_blob_client = BlobStorageClient(
    settings.AZURE_STORAGE_CONNECTION_STRING,
    settings.AZURE_STORAGE_CONTAINER,
)
_case_repository = CaseRepository(_blob_client)
_case_read_repository = CaseReadRepository(
    settings.AZURE_STORAGE_CONNECTION_STRING,
    settings.AZURE_STORAGE_CONTAINER,
)
_embedding_client = EmbeddingClient()

_search_index = CaseSearchIndex(
    endpoint=settings.AZURE_SEARCH_ENDPOINT,
    index_name=settings.CASE_INDEX_NAME,
    admin_key=settings.AZURE_SEARCH_ADMIN_KEY,
)
_evidence_search_index = EvidenceSearchIndex(
    endpoint=settings.AZURE_SEARCH_ENDPOINT,
    index_name=settings.EVIDENCE_INDEX_NAME,
    admin_key=settings.AZURE_SEARCH_ADMIN_KEY,
)
_knowledge_search_index = KnowledgeSearchIndex(
    endpoint=settings.AZURE_SEARCH_ENDPOINT,
    index_name=settings.KNOWLEDGE_INDEX_NAME,
    admin_key=settings.AZURE_SEARCH_ADMIN_KEY,
)


def _validate_search_indexes_exist() -> None:
    client = SearchIndexClient(
        endpoint=settings.AZURE_SEARCH_ENDPOINT,
        credential=AzureKeyCredential(settings.AZURE_SEARCH_ADMIN_KEY),
    )
    for index_name in (
        settings.CASE_INDEX_NAME,
        settings.EVIDENCE_INDEX_NAME,
        settings.KNOWLEDGE_INDEX_NAME,
    ):
        try:
            client.get_index(index_name)
        except ResourceNotFoundError as exc:
            raise ValueError(f"Search index does not exist: {index_name}") from exc


_validate_search_indexes_exist()

_case_ingestion = CaseIngestionService(
    search_index=_search_index,
    case_repository=_case_read_repository,
    embedding_client=_embedding_client,
)
_case_entry = CaseEntryService(_case_repository)
_evidence_ingestion = EvidenceIngestionService(
    _case_repository, _embedding_client, _evidence_search_index
)
_knowledge_ingestion = KnowledgeIngestionService(
    _blob_client, _embedding_client, _knowledge_search_index
)
_case_search_client = CaseSearchClient(
    endpoint=settings.AZURE_SEARCH_ENDPOINT,
    index_name=settings.CASE_INDEX_NAME,
    admin_key=settings.AZURE_SEARCH_ADMIN_KEY,
)
_evidence_search_client = EvidenceSearchClient(
    endpoint=settings.AZURE_SEARCH_ENDPOINT,
    index_name=settings.EVIDENCE_INDEX_NAME,
    admin_key=settings.AZURE_SEARCH_ADMIN_KEY,
)
_knowledge_search_client = KnowledgeSearchClient(
    endpoint=settings.AZURE_SEARCH_ENDPOINT,
    index_name=settings.KNOWLEDGE_INDEX_NAME,
    admin_key=settings.AZURE_SEARCH_ADMIN_KEY,
)
_kpi_tool = KPITool(
    case_search_client=_case_search_client,
    settings=settings,
    case_repo=_case_read_repository,
)
_entry_handler = EntryHandler(
    case_entry=_case_entry,
    evidence_ingestion=_evidence_ingestion,
    case_ingestion=_case_ingestion,
    knowledge_ingestion=_knowledge_ingestion,
    unified_graph=compiled_graph,
    llm_client=get_llm("intent", temperature=0.4),
)


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------
app = FastAPI(title="ValueSims Decision Support API", debug=True)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5500",
        "http://localhost:5500",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes.router)
app.include_router(
    build_support_router(
        entry_handler=_entry_handler,
        case_repository=_case_repository,
        case_search_client=_case_search_client,
        knowledge_search_client=_knowledge_search_client,
        blob_client=_blob_client,
        kpi_tool=_kpi_tool,
    )
)


__all__ = ["app"]
