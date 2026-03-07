from __future__ import annotations

import os
from typing import Optional

from pydantic.v1 import BaseSettings, Field


class Settings(BaseSettings):
    AZURE_SEARCH_ENDPOINT: str = Field(
        "",
        env="AZURE_SEARCH_ENDPOINT",
        description="Azure AI Search endpoint URL.",
    )
    AZURE_SEARCH_ADMIN_KEY: str = Field(
        "",
        env="AZURE_SEARCH_ADMIN_KEY",
        description="Azure AI Search admin API key.",
    )
    AZURE_STORAGE_CONNECTION_STRING: str = Field(
        "",
        env="AZURE_STORAGE_CONNECTION_STRING",
        description="Azure Blob Storage connection string.",
    )
    AZURE_STORAGE_CONTAINER: str = Field(
        "",
        env="AZURE_STORAGE_CONTAINER",
        description="Azure Blob Storage container name.",
    )

    CASE_INDEX_NAME: str = Field(
        "",
        env="CASE_INDEX_NAME",
        description="Azure AI Search index name for cases.",
    )
    EVIDENCE_INDEX_NAME: str = Field(
        "",
        env="EVIDENCE_INDEX_NAME",
        description="Azure AI Search index name for evidence.",
    )
    KNOWLEDGE_INDEX_NAME: str = Field(
        "",
        env="KNOWLEDGE_INDEX_NAME",
        description="Azure AI Search index name for knowledge documents.",
    )

    RETRIEVAL_SIMILAR_CASES_TOP_K: int = Field(
        5,
        env="RETRIEVAL_SIMILAR_CASES_TOP_K",
        description="Default top-k results for similar case retrieval.",
    )
    RETRIEVAL_PATTERN_CASES_TOP_K: int = Field(
        20,
        env="RETRIEVAL_PATTERN_CASES_TOP_K",
        description="Default top-k results for pattern analysis case retrieval.",
    )
    RETRIEVAL_KPI_CASES_TOP_K: int = Field(
        100,
        env="RETRIEVAL_KPI_CASES_TOP_K",
        description="Default top-k results for KPI case retrieval.",
    )
    RETRIEVAL_KNOWLEDGE_TOP_K: int = Field(
        10,
        env="RETRIEVAL_KNOWLEDGE_TOP_K",
        description="Default top-k results for knowledge retrieval.",
    )
    RETRIEVAL_EVIDENCE_TOP_K: int = Field(
        20,
        env="RETRIEVAL_EVIDENCE_TOP_K",
        description="Default top-k results for evidence retrieval.",
    )
    AZURE_OPENAI_CHAT_DEPLOYMENT: str = Field(
        "",
        env="AZURE_OPENAI_CHAT_DEPLOYMENT",
        description="Azure OpenAI chat deployment name for reasoning workflows.",
    )
    LLM_MODEL_CLASSIFIER: str = Field(
        "",
        env="LLM_MODEL_CLASSIFIER",
        description="Model deployment used by intent classification node.",
    )
    LLM_MODEL_OPERATIONAL: str = Field(
        "",
        env="LLM_MODEL_OPERATIONAL",
        description="Model deployment used by operational reasoning/reflection nodes.",
    )
    LLM_MODEL_SIMILARITY: str = Field(
        "",
        env="LLM_MODEL_SIMILARITY",
        description="Model deployment used by similarity reasoning/reflection nodes.",
    )
    LLM_MODEL_STRATEGY: str = Field(
        "",
        env="LLM_MODEL_STRATEGY",
        description="Model deployment used by strategy reasoning/reflection nodes.",
    )
    LLM_MODEL_KPI_REFLECTION: str = Field(
        "",
        env="LLM_MODEL_KPI_REFLECTION",
        description="Model deployment used by KPI reflection node.",
    )
    MODEL_INTENT_CLASSIFIER: str = Field(
        "",
        env="MODEL_INTENT_CLASSIFIER",
        description="Adaptive policy base model for intent classification and default fallback.",
    )
    MODEL_OPERATIONAL: str = Field(
        "",
        env="MODEL_OPERATIONAL",
        description="Adaptive policy base model for operational reasoning.",
    )
    MODEL_OPERATIONAL_PREMIUM: str = Field(
        "",
        env="MODEL_OPERATIONAL_PREMIUM",
        description="Adaptive policy premium model for operational escalation.",
    )
    MODEL_STRATEGY: str = Field(
        "",
        env="MODEL_STRATEGY",
        description="Adaptive policy base model for strategy reasoning.",
    )
    MODEL_STRATEGY_PREMIUM: str = Field(
        "",
        env="MODEL_STRATEGY_PREMIUM",
        description="Adaptive policy premium model for strategy escalation.",
    )
    APPLICATIONINSIGHTS_CONNECTION_STRING: Optional[str] = Field(
        None,
        env="APPLICATIONINSIGHTS_CONNECTION_STRING",
        description="Azure Monitor Application Insights connection string for distributed tracing.",
    )

    class Config(BaseSettings.Config):
        env_file = ".env"


from dotenv import load_dotenv

load_dotenv(override=True)

settings = Settings(
    AZURE_SEARCH_ENDPOINT=os.getenv("AZURE_SEARCH_ENDPOINT", ""),
    AZURE_SEARCH_ADMIN_KEY=os.getenv("AZURE_SEARCH_ADMIN_KEY", ""),
    AZURE_STORAGE_CONNECTION_STRING=os.getenv("AZURE_STORAGE_CONNECTION_STRING", ""),
    AZURE_STORAGE_CONTAINER=os.getenv("AZURE_STORAGE_CONTAINER", ""),
    CASE_INDEX_NAME=os.getenv("CASE_INDEX_NAME", ""),
    EVIDENCE_INDEX_NAME=os.getenv("EVIDENCE_INDEX_NAME", ""),
    KNOWLEDGE_INDEX_NAME=os.getenv("KNOWLEDGE_INDEX_NAME", ""),
    RETRIEVAL_SIMILAR_CASES_TOP_K=int(os.getenv("RETRIEVAL_SIMILAR_CASES_TOP_K", "5")),
    RETRIEVAL_PATTERN_CASES_TOP_K=int(os.getenv("RETRIEVAL_PATTERN_CASES_TOP_K", "20")),
    RETRIEVAL_KPI_CASES_TOP_K=int(os.getenv("RETRIEVAL_KPI_CASES_TOP_K", "100")),
    RETRIEVAL_KNOWLEDGE_TOP_K=int(os.getenv("RETRIEVAL_KNOWLEDGE_TOP_K", "10")),
    RETRIEVAL_EVIDENCE_TOP_K=int(os.getenv("RETRIEVAL_EVIDENCE_TOP_K", "20")),
    AZURE_OPENAI_CHAT_DEPLOYMENT=os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", ""),
    LLM_MODEL_CLASSIFIER=os.getenv("LLM_MODEL_CLASSIFIER", ""),
    LLM_MODEL_OPERATIONAL=os.getenv("LLM_MODEL_OPERATIONAL", ""),
    LLM_MODEL_SIMILARITY=os.getenv("LLM_MODEL_SIMILARITY", ""),
    LLM_MODEL_STRATEGY=os.getenv("LLM_MODEL_STRATEGY", ""),
    LLM_MODEL_KPI_REFLECTION=os.getenv("LLM_MODEL_KPI_REFLECTION", ""),
    MODEL_INTENT_CLASSIFIER=os.getenv(
        "MODEL_INTENT_CLASSIFIER",
        os.getenv("LLM_MODEL_CLASSIFIER", ""),
    ),
    MODEL_OPERATIONAL=os.getenv(
        "MODEL_OPERATIONAL",
        os.getenv("LLM_MODEL_OPERATIONAL", ""),
    ),
    MODEL_OPERATIONAL_PREMIUM=os.getenv(
        "MODEL_OPERATIONAL_PREMIUM",
        os.getenv("LLM_MODEL_OPERATIONAL", ""),
    ),
    MODEL_STRATEGY=os.getenv(
        "MODEL_STRATEGY",
        os.getenv("LLM_MODEL_STRATEGY", ""),
    ),
    MODEL_STRATEGY_PREMIUM=os.getenv(
        "MODEL_STRATEGY_PREMIUM",
        os.getenv("LLM_MODEL_STRATEGY", ""),
    ),
    APPLICATIONINSIGHTS_CONNECTION_STRING=os.getenv(
        "APPLICATIONINSIGHTS_CONNECTION_STRING"
    ),
)

__all__ = ["Settings", "settings"]
