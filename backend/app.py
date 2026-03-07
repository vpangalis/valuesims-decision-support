from __future__ import annotations

from dotenv import load_dotenv

load_dotenv(override=True)

from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import ResourceNotFoundError
from azure.search.documents.indexes import SearchIndexClient
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.ai.escalation_controller import EscalationController
from backend.ai.model_policy import ModelPolicy
from backend.config import settings
from backend.api.routes import ApiRoutes
from backend.entry.entry_handler import EntryHandler
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
from backend.workflow.nodes.context_node import ContextNode
from backend.workflow.nodes.end_node import EndNode
from backend.workflow.nodes.intent_classification_node import IntentClassificationNode
from backend.workflow.nodes.question_readiness_node import QuestionReadinessNode
from backend.workflow.nodes.kpi_node import KPINode
from backend.workflow.nodes.kpi_reflection_node import KPIReflectionNode
from backend.workflow.nodes.operational_node import OperationalNode
from backend.workflow.nodes.operational_escalation_node import OperationalEscalationNode
from backend.workflow.nodes.operational_reflection_node import OperationalReflectionNode
from backend.workflow.nodes.response_formatter_node import ResponseFormatterNode
from backend.workflow.nodes.router_node import RouterNode
from backend.workflow.nodes.similarity_node import SimilarityNode
from backend.workflow.nodes.similarity_reflection_node import SimilarityReflectionNode
from backend.workflow.nodes.start_node import StartNode
from backend.workflow.nodes.strategy_node import StrategyNode
from backend.workflow.nodes.strategy_escalation_node import StrategyEscalationNode
from backend.workflow.nodes.strategy_reflection_node import StrategyReflectionNode
from backend.workflow.unified_incident_graph import UnifiedIncidentGraph


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
        self.hybrid_retriever = HybridRetriever(
            case_search_client=self.case_search_client,
            evidence_search_client=self.evidence_search_client,
            knowledge_search_client=self.knowledge_search_client,
            embedding_client=self.embedding_client,
            settings=settings,
        )
        self.model_policy = ModelPolicy(settings=settings)
        self.escalation_controller = EscalationController()
        self.classifier_llm = get_llm(deployment=settings.LLM_MODEL_CLASSIFIER, temperature=0.0)

        self.operational_llm = get_llm(deployment=settings.LLM_MODEL_OPERATIONAL, temperature=0.2)
        self.operational_reflection_llm = get_llm(deployment=settings.LLM_MODEL_OPERATIONAL, temperature=0.0)
        self.similarity_llm = get_llm(deployment=settings.LLM_MODEL_SIMILARITY, temperature=0.1)
        self.similarity_reflection_llm = get_llm(deployment=settings.LLM_MODEL_SIMILARITY, temperature=0.0)
        self.strategy_llm = get_llm(deployment=settings.LLM_MODEL_STRATEGY, temperature=0.2)
        self.strategy_reflection_llm = get_llm(deployment=settings.LLM_MODEL_STRATEGY, temperature=0.0)
        self.kpi_reflection_llm = get_llm(deployment=settings.LLM_MODEL_KPI_REFLECTION, temperature=0.1)

        self.kpi_tool = KPITool(
            hybrid_retriever=self.hybrid_retriever,
            settings=settings,
            case_repo=self.case_read_repository,
        )

        self.intent_classification_node = IntentClassificationNode(
            llm_client=self.classifier_llm
        )
        self.question_readiness_llm = get_llm(deployment=settings.LLM_MODEL_CLASSIFIER, temperature=0.0)
        self.question_readiness_node = QuestionReadinessNode(
            llm_client=self.question_readiness_llm
        )
        self.start_node = StartNode()
        self.context_node = ContextNode(case_entry_service=self.case_entry)
        self.router_node = RouterNode()
        self.response_formatter_node = ResponseFormatterNode()
        self.end_node = EndNode()

        self.operational_node = OperationalNode(
            hybrid_retriever=self.hybrid_retriever,
            llm_client=self.operational_llm,
            settings=settings,
        )
        self.operational_escalation_node = OperationalEscalationNode(
            operational_node=self.operational_node,
            model_policy=self.model_policy,
        )
        self.operational_reflection_node = OperationalReflectionNode(
            llm_client=self.operational_reflection_llm,
            regeneration_llm_client=self.operational_llm,
        )
        self.similarity_node = SimilarityNode(
            hybrid_retriever=self.hybrid_retriever,
            llm_client=self.similarity_llm,
            settings=settings,
        )
        self.similarity_reflection_node = SimilarityReflectionNode(
            llm_client=self.similarity_reflection_llm,
            regeneration_llm_client=self.similarity_llm,
        )
        self.strategy_node = StrategyNode(
            hybrid_retriever=self.hybrid_retriever,
            llm_client=self.strategy_llm,
            settings=settings,
        )
        self.strategy_escalation_node = StrategyEscalationNode(
            strategy_node=self.strategy_node,
            model_policy=self.model_policy,
        )
        self.strategy_reflection_node = StrategyReflectionNode(
            llm_client=self.strategy_reflection_llm,
            regeneration_llm_client=self.strategy_llm,
        )
        self.kpi_node = KPINode(kpi_tool=self.kpi_tool, settings=settings)
        self.kpi_reflection_node = KPIReflectionNode(
            llm_client=self.kpi_reflection_llm,
            regeneration_llm_client=self.kpi_reflection_llm,
        )

        self.unified_graph = UnifiedIncidentGraph(
            start_node=self.start_node,
            context_node=self.context_node,
            intent_classification_node=self.intent_classification_node,
            question_readiness_node=self.question_readiness_node,
            router_node=self.router_node,
            operational_node=self.operational_node,
            operational_reflection_node=self.operational_reflection_node,
            operational_escalation_node=self.operational_escalation_node,
            similarity_node=self.similarity_node,
            similarity_reflection_node=self.similarity_reflection_node,
            strategy_node=self.strategy_node,
            strategy_reflection_node=self.strategy_reflection_node,
            strategy_escalation_node=self.strategy_escalation_node,
            kpi_node=self.kpi_node,
            kpi_reflection_node=self.kpi_reflection_node,
            response_formatter_node=self.response_formatter_node,
            end_node=self.end_node,
            escalation_controller=self.escalation_controller,
        )

        self.entry_handler = EntryHandler(
            case_entry=self.case_entry,
            evidence_ingestion=self.evidence_ingestion,
            case_ingestion=self.case_ingestion,
            knowledge_ingestion=self.knowledge_ingestion,
            unified_graph=self.unified_graph,
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

        @app.on_event("shutdown")
        async def _flush_langfuse():
            from backend.tracing import flush_langfuse
            flush_langfuse()

        self.app = app


app = BackendApp().app

__all__ = ["app"]
