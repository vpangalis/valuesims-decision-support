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
from backend.ai.model_strategy import ModelStrategy
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
from backend.infra.language_model_client import LanguageModelClient
from backend.infra.llm_logging_client import LoggedLanguageModelClient
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
from backend.tools.kpi_tool import KPITool, KPIAnalyticsTool
from backend.workflow.nodes.context_node import ContextNode
from backend.workflow.nodes.end_node import EndNode
from backend.workflow.nodes.intent_classification_node import IntentClassificationNode
from backend.workflow.nodes.intent_reflection_node import IntentReflectionNode
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
        self.language_model_client = LanguageModelClient(settings_module=settings)
        self.model_strategy = ModelStrategy(settings=settings)
        self.model_policy = ModelPolicy(model_strategy=self.model_strategy)
        self.escalation_controller = EscalationController()
        self.classifier_llm = LoggedLanguageModelClient(
            base_client=self.language_model_client,
            settings=settings,
            node_name="intent_classification",
            model_name=settings.LLM_MODEL_CLASSIFIER,
        )
        self.intent_reflection_llm = LoggedLanguageModelClient(
            base_client=self.language_model_client,
            settings=settings,
            node_name="intent_reflection",
            model_name=settings.LLM_MODEL_CLASSIFIER,
        )
        self.operational_llm = LoggedLanguageModelClient(
            base_client=self.language_model_client,
            settings=settings,
            node_name="operational_reasoning",
            model_name=settings.LLM_MODEL_OPERATIONAL,
        )
        self.operational_reflection_llm = LoggedLanguageModelClient(
            base_client=self.language_model_client,
            settings=settings,
            node_name="operational_reflection",
            model_name=settings.LLM_MODEL_OPERATIONAL,
        )
        self.similarity_llm = LoggedLanguageModelClient(
            base_client=self.language_model_client,
            settings=settings,
            node_name="similarity_reasoning",
            model_name=settings.LLM_MODEL_SIMILARITY,
        )
        self.similarity_reflection_llm = LoggedLanguageModelClient(
            base_client=self.language_model_client,
            settings=settings,
            node_name="similarity_reflection",
            model_name=settings.LLM_MODEL_SIMILARITY,
        )
        self.strategy_llm = LoggedLanguageModelClient(
            base_client=self.language_model_client,
            settings=settings,
            node_name="strategy_reasoning",
            model_name=settings.LLM_MODEL_STRATEGY,
        )
        self.strategy_reflection_llm = LoggedLanguageModelClient(
            base_client=self.language_model_client,
            settings=settings,
            node_name="strategy_reflection",
            model_name=settings.LLM_MODEL_STRATEGY,
        )
        self.kpi_reflection_llm = LoggedLanguageModelClient(
            base_client=self.language_model_client,
            settings=settings,
            node_name="kpi_reflection",
            model_name=settings.LLM_MODEL_KPI_REFLECTION,
        )

        self.kpi_tool = KPITool(
            hybrid_retriever=self.hybrid_retriever,
            settings=settings,
        )

        self.intent_classification_node = IntentClassificationNode(
            llm_client=self.classifier_llm
        )
        self.question_readiness_llm = LoggedLanguageModelClient(
            base_client=self.language_model_client,
            settings=settings,
            node_name="question_readiness",
            model_name=settings.LLM_MODEL_CLASSIFIER,
        )
        self.question_readiness_node = QuestionReadinessNode(
            llm_client=self.question_readiness_llm
        )
        self.intent_reflection_node = IntentReflectionNode(
            llm_client=self.intent_reflection_llm,
            regeneration_llm_client=self.classifier_llm,
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
            intent_reflection_node=self.intent_reflection_node,
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
            llm_client=self.language_model_client,
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
        )
        app.include_router(routes.router())
        self.app = app


app = BackendApp().app

__all__ = ["app"]
