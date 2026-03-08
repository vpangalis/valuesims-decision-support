from __future__ import annotations

from dotenv import load_dotenv

load_dotenv(override=True)

from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import ResourceNotFoundError
from azure.search.documents.indexes import SearchIndexClient
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import settings
from backend.api.routes import ApiRoutes
from backend.entry.entry_handler import EntryHandler
from backend.graph import compiled_graph
from backend.infra.blob_storage import (
    BlobStorageClient,
    CaseRepository,
    CaseReadRepository,
)
from backend.infra.embeddings import EmbeddingClient
from backend.infra.case_search_client import CaseSearchClient
from backend.infra.evidence_search_client import EvidenceSearchClient
from backend.llm import get_llm
from backend.infra.knowledge_search_client import KnowledgeSearchClient
from backend.ingestion.case_ingestion import (
    CaseEntryService,
    CaseIngestionService,
    CaseSearchIndex,
)
from backend.ingestion.evidence_ingestion import (
    EvidenceIngestionService,
    EvidenceSearchIndex,
)
from backend.ingestion.knowledge_ingestion import (
    KnowledgeIngestionService,
    KnowledgeSearchIndex,
)
from backend.retrieval.hybrid_retriever import HybridRetriever
from backend.tools.kpi_tool import KPITool
from backend.workflow.nodes.kpi_reflection_node import KPIReflectionNode


class BackendContainer:
    def __init__(self) -> None:
        self.blob_client = BlobStorageClient(
            settings.AZURE_STORAGE_CONNECTION_STRING,
            settings.AZURE_STORAGE_CONTAINER,
        )
        self.case_repository = CaseRepository(self.blob_client)
        self.case_read_repository = CaseReadRepository(
            settings.AZURE_STORAGE_CONNECTION_STRING,
            settings.AZURE_STORAGE_CONTAINER,
        )
        self.embedding_client = EmbeddingClient()
        self.search_index = CaseSearchIndex(
            endpoint=settings.AZURE_SEARCH_ENDPOINT,
            index_name=settings.CASE_INDEX_NAME,
            admin_key=settings.AZURE_SEARCH_ADMIN_KEY,
        )
        self.evidence_search_index = EvidenceSearchIndex(
            endpoint=settings.AZURE_SEARCH_ENDPOINT,
            index_name=settings.EVIDENCE_INDEX_NAME,
            admin_key=settings.AZURE_SEARCH_ADMIN_KEY,
        )
        self.knowledge_search_index = KnowledgeSearchIndex(
            endpoint=settings.AZURE_SEARCH_ENDPOINT,
            index_name=settings.KNOWLEDGE_INDEX_NAME,
            admin_key=settings.AZURE_SEARCH_ADMIN_KEY,
        )
        self._validate_search_indexes_exist()

        self.case_ingestion = CaseIngestionService(
            search_index=self.search_index,
            case_repository=self.case_read_repository,
            embedding_client=self.embedding_client,
        )
        self.case_entry = CaseEntryService(self.case_repository)
        self.evidence_ingestion = EvidenceIngestionService(
            self.case_repository,
            self.embedding_client,
            self.evidence_search_index,
        )
        self.knowledge_ingestion = KnowledgeIngestionService(
            self.blob_client,
            self.embedding_client,
            self.knowledge_search_index,
        )
        self.case_search_client = CaseSearchClient(
            endpoint=settings.AZURE_SEARCH_ENDPOINT,
            index_name=settings.CASE_INDEX_NAME,
            admin_key=settings.AZURE_SEARCH_ADMIN_KEY,
        )
        self.evidence_search_client = EvidenceSearchClient(
            endpoint=settings.AZURE_SEARCH_ENDPOINT,
            index_name=settings.EVIDENCE_INDEX_NAME,
            admin_key=settings.AZURE_SEARCH_ADMIN_KEY,
        )
        self.knowledge_search_client = KnowledgeSearchClient(
            endpoint=settings.AZURE_SEARCH_ENDPOINT,
            index_name=settings.KNOWLEDGE_INDEX_NAME,
            admin_key=settings.AZURE_SEARCH_ADMIN_KEY,
        )
        # DEPRECATED: HybridRetriever kept only for KPITool until KPITool is refactored
        self.hybrid_retriever = HybridRetriever(
            case_search_client=self.case_search_client,
            evidence_search_client=self.evidence_search_client,
            knowledge_search_client=self.knowledge_search_client,
            embedding_client=self.embedding_client,
            settings=settings,
        )

        self.kpi_tool = KPITool(
            hybrid_retriever=self.hybrid_retriever,
            settings=settings,
            case_repo=self.case_read_repository,
        )
        self.kpi_reflection_llm = get_llm(deployment=settings.LLM_MODEL_KPI_REFLECTION, temperature=0.1)
        # DEPRECATED: KPIReflectionNode class kept only for /cases/kpi/assessment route
        self.kpi_reflection_node = KPIReflectionNode(
            llm_client=self.kpi_reflection_llm,
            regeneration_llm_client=self.kpi_reflection_llm,
        )

        self.entry_handler = EntryHandler(
            case_entry=self.case_entry,
            evidence_ingestion=self.evidence_ingestion,
            case_ingestion=self.case_ingestion,
            knowledge_ingestion=self.knowledge_ingestion,
            unified_graph=compiled_graph,
            llm_client=get_llm(temperature=0.4),
        )

    def _validate_search_indexes_exist(self) -> None:
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


class BackendApp:
    def __init__(self) -> None:
        import os
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry import trace as otel_trace

        _otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        if _otlp_endpoint:
            _otlp_exporter = OTLPSpanExporter(endpoint=_otlp_endpoint, insecure=True)
            _provider = otel_trace.get_tracer_provider()
            if hasattr(_provider, "add_span_processor"):
                _provider.add_span_processor(BatchSpanProcessor(_otlp_exporter))

        container = BackendContainer()
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

        routes = ApiRoutes(
            entry_handler=container.entry_handler,
            case_repository=container.case_repository,
            case_search_client=container.case_search_client,
            knowledge_search_client=container.knowledge_search_client,
            blob_client=container.blob_client,
            kpi_tool=container.kpi_tool,
            kpi_reflection_node=container.kpi_reflection_node,
        )
        app.include_router(routes.router())

        self.app = app


app = BackendApp().app

__all__ = ["app"]
