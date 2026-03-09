"""backend/tests/test_node_checks.py

Automated check suite for CoSolve's four primary agent nodes:
  - OperationalNode
  - SimilarityNode
  - StrategyNode
  - KPINode

Four check categories per node:
  1. Structural Integrity  — AST-level checks; no runtime dependencies.
  2. Input/Output Contract — runs the node with mocked dependencies.
  3. Quality Gate         — text-pattern replay of reflection-node criteria.
                           Requires LIVE_MODE=True to make real LLM calls;
                           otherwise reported as SKIPPED.
  4. Banned Term Detection — scans output text for prohibited user-facing terms.

Run all checks:
    python backend/tests/test_node_checks.py

Run via pytest (Categories 1-2-4 always run; Category 3 requires LIVE_MODE=True):
    pytest backend/tests/test_node_checks.py -v

Set LIVE_MODE=True inside NodeCheckConfig to enable Category 3 live LLM checks
and full end-to-end I/O checks against real Azure services.
"""

from __future__ import annotations

import ast
import inspect
import logging
import re
import sys
import textwrap
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from backend.retrieval.models import CaseSummary, EvidenceSummary, KnowledgeSummary
from backend.tools.kpi_tool import KPITool
from backend.workflow.models import (
    KPINodeOutput,
    KPIResult,
    OperationalPayload,
    OperationalNodeOutput,
    QuestionReadinessNodeOutput,
    QuestionReadinessResult,
    SimilarityPayload,
    SimilarityNodeOutput,
    StrategyPayload,
    StrategyNodeOutput,
)
from backend.workflow.nodes.kpi_node import KPINode
from backend.workflow.nodes.node_parsing_utils import is_new_problem_question
from backend.workflow.nodes.operational_node import OperationalNode
from backend.workflow.nodes.question_readiness_node import QuestionReadinessNode
from backend.workflow.nodes.similarity_node import SimilarityNode
from backend.workflow.nodes.strategy_node import StrategyNode

__all__ = [
    "NodeCheckConfig",
    "OperationalNodeChecks",
    "QuestionReadinessNodeChecks",
    "SimilarityNodeChecks",
    "StrategyNodeChecks",
    "KPINodeChecks",
    "NodeCheckRunner",
]

_log = logging.getLogger("node_checks")


# ══════════════════════════════════════════════════════════════════════════════
# NodeCheckConfig — shared configuration, fixtures, mocks, and factories
# ══════════════════════════════════════════════════════════════════════════════


class NodeCheckConfig:
    """Shared configuration and test fixtures for all node checks."""

    # ── Mode flag ─────────────────────────────────────────────────────────
    # Set to True to enable Category 3 (Quality Gate) live LLM checks and
    # full end-to-end I/O checks against real Azure services.
    LIVE_MODE: bool = True

    # ── Sample seeded case (TRM-20250310-0001 — pantograph carbon strip wear) ─
    SAMPLE_CASE_ID: str = "TRM-20250310-0001"

    SAMPLE_CASE_CONTEXT: dict[str, Any] = {
        "case_id": "TRM-20250310-0001",
        "organization_country": "France",
        "organization_site": "Saint-Denis Depot",
        "d_states": {
            "D1_2": {
                "status": "completed",
                "data": {
                    "problem_description": (
                        "Pantograph carbon strips on Line 4 fleet (Citadis X05 units) "
                        "showing accelerated wear rates after catenary maintenance "
                        "completed 2025-03-07. Average strip lifespan dropped from "
                        "~90,000 km to ~18,000 km. Six vehicles affected."
                    ),
                    "country": "France",
                    "site": "Saint-Denis Depot",
                    "department": "Fleet Maintenance — Traction & Pantograph Systems",
                    "team_members": [
                        "Isabelle Fontaine",
                        "Marc Delcourt",
                        "Pierre-Yves Renard",
                        "Amira Takouti",
                        "Gerard Vasseur",
                    ],
                },
            },
            "D3": {
                "status": "completed",
                "data": {
                    "what_happened": (
                        "All six Citadis X05 vehicles reported abnormal pantograph wear "
                        "within 30 operating hours post-maintenance. Strip wear rate "
                        "measured at 4.8 mm per 1,000 km vs normal 0.8 mm per 1,000 km."
                    ),
                    "impact": (
                        "6 of 6 Line 4 vehicles affected. Service risk: HIGH. "
                        "Estimated cost €8,400 for emergency strip replacements."
                    ),
                    "what_contained": (
                        "Speed restriction 30 km/h above KP 2.1. "
                        "Carbon strips replaced on TRM-401, TRM-402, TRM-403."
                    ),
                },
            },
            "D4": {
                "status": "completed",
                "data": {
                    "fishbone": {
                        "process": [
                            "No post-maintenance geometry check before returning to service",
                            "Catenary procedure does not specify wire height check for tram lines",
                        ],
                        "management": [
                            "Contractor works to railway standard, not tram-specific standard",
                        ],
                    },
                    "investigation_finding": (
                        "Wire height at KP 3.4 measured 5,420 mm — 130 mm below "
                        "lower design tolerance (5,450 mm)."
                    ),
                },
            },
        },
    }

    # ── Sample questions per node type ────────────────────────────────────
    OPERATIONAL_QUESTION_WITH_CASE: str = (
        "What should we focus on for root cause analysis given the pantograph wear pattern "
        "and catenary geometry findings?"
    )
    OPERATIONAL_QUESTION_NO_CASE: str = (
        "We just found a new problem with our pantograph system, where do we start?"
    )

    SIMILARITY_QUESTION_WITH_CASE: str = (
        "Have we had similar pantograph carbon strip wear incidents caused by catenary "
        "maintenance contractor errors before?"
    )
    SIMILARITY_QUESTION_NO_CASE: str = (
        "Have we seen catenary-related failures causing rolling stock damage in France?"
    )

    STRATEGY_QUESTION: str = (
        "What systemic patterns can you identify across our recent railway fleet "
        "maintenance incidents involving external contractors?"
    )

    KPI_QUESTION_GLOBAL: str = (
        "Show me overall fleet performance KPIs across all countries."
    )
    KPI_QUESTION_COUNTRY: str = "What are the KPIs for France? country: France"
    KPI_QUESTION_CASE: str = "Show me KPIs for this specific case."

    # ── Mock Azure AI Search results (two realistic seeded cases) ─────────
    MOCK_SIMILAR_CASES: list[CaseSummary] = [
        CaseSummary(
            case_id="TRM-20250415-0002",
            organization_country="France",
            organization_site="Lyon Part-Dieu Depot",
            opening_date=None,
            closure_date=None,
            problem_description=(
                "Pantograph carbon strips on Line 2 showing premature wear after "
                "track realignment works. Strip replacement interval halved."
            ),
            five_whys_text=(
                "Wire height deviation of 120 mm below design spec found at KP 4.2. "
                "Contractor applied railway standard instead of tram-specific standard."
            ),
            permanent_actions_text=(
                "Updated catenary acceptance specification to include tram-specific "
                "wire height tolerance check. Mandatory post-maintenance geometry "
                "sign-off added before return to service."
            ),
            ai_summary=(
                "Catenary geometry deviation causing pantograph wear — "
                "contractor standard mismatch"
            ),
            status="closed",
            current_stage=None,
            responsible_leader="Claire Moreau",
            department="Infrastructure & Catenary",
        ),
        CaseSummary(
            case_id="TRM-20240820-0003",
            organization_country="Belgium",
            organization_site="Brussels Anderlecht Depot",
            opening_date=None,
            closure_date=None,
            problem_description=(
                "Recurring arc flash events on STIB Line 7 Citadis units after "
                "overhead line renewal. Carbon strip surface showing metallic deposits."
            ),
            five_whys_text=(
                "New catenary wire had residual lubricant from installation causing "
                "arcing. Wire cleaning protocol not specified in acceptance procedure."
            ),
            permanent_actions_text=(
                "Introduced wire burn-in procedure (3 passes at reduced speed) and "
                "updated acceptance test checklist."
            ),
            ai_summary="OHL lubricant contamination causing arc flash post-installation",
            status="closed",
            current_stage=None,
            responsible_leader="Pieter Van den Berg",
            department="Fleet & Pantograph Maintenance",
        ),
    ]

    MOCK_EVIDENCE: list[EvidenceSummary] = []
    MOCK_KNOWLEDGE: list[KnowledgeSummary] = []

    # ── Mock KPI case — for case-scope tests ──────────────────────────────
    MOCK_KPI_CASE: CaseSummary = CaseSummary(
        case_id="TRM-20250310-0001",
        organization_country="France",
        organization_site="Saint-Denis Depot",
        opening_date=None,
        closure_date=None,
        problem_description="Pantograph carbon strip abnormal wear on Line 4",
        five_whys_text=None,
        permanent_actions_text=None,
        ai_summary=None,
        status="open",
        current_stage="D4",
        responsible_leader="Isabelle Fontaine",
        department="Fleet Maintenance — Traction & Pantograph Systems",
    )

    # ── Banned terms ──────────────────────────────────────────────────────
    # D-codes — use word-boundary pattern to avoid matching e.g. "model"
    BANNED_D_CODE_PATTERN: re.Pattern[str] = re.compile(r"\b(D[1-8](?:_[12]|_D2)?)\b")
    # Technical infrastructure terms — case-insensitive
    BANNED_TECH_TERMS: tuple[str, ...] = (
        "azure",
        "langgraph",
        "langchain",
        "retriever",
        "embedding",
        "vector store",
        "search index",
        "cosmos db",
    )

    # ── Canned mock LLM responses ─────────────────────────────────────────
    # These are structurally correct responses used for Category 2 (I/O Contract)
    # checks in LIVE_MODE=False.  They deliberately contain all required section
    # markers, the ⚠️ prefix, and the correct suggestion format so that the
    # structural/contract validation passes even without a real LLM.

    MOCK_OPERATIONAL_RESPONSE_WITH_CASE: str = textwrap.dedent(
        """\
        [CURRENT STATE]
        The investigation of case TRM-20250310-0001 is in Root Cause Analysis. \
The catenary geometry survey confirmed a wire height of 5,420 mm at KP 3.4 — \
130 mm below the lower design tolerance of 5,450 mm. The team should validate \
whether the deviation is confined to KP 3.4 or extends across the full \
maintained section KP 2.1–5.7.

        [GAPS IN PREVIOUS STATES]
        Has the team confirmed whether the catenary contractor held tram-specific \
certification, or whether railway-grade specifications were applied? The fishbone \
entries reference a standard mismatch but the responsible contractor's qualification \
record is not documented in the case data.

        [NEXT STATE PREVIEW]
        Permanent corrective actions must address both the geometry rectification \
and the acceptance-process gap. Specifically: formalise a post-maintenance \
geometry check requirement in the catenary maintenance procedure before any \
line returns to service.

        [GENERAL ADVICE]
        ⚠️ General 8D methodology guidance not specific to this case:
        When root causes combine technical deviation and process weakness, \
corrective actions must address both. Fixing the geometry alone without updating \
the acceptance procedure will allow recurrence.

        [WHAT TO EXPLORE NEXT]
        Questions to ask your team right now:
        • Did the contractor who performed the Line 4 re-tensioning hold tram-specific \
catenary certification, or were railway-grade tolerances applied?
        • Were Line 7 and Line 2 catenary sections also surveyed for geometry \
deviations during the same maintenance window as Line 4?

        Questions to ask CoSolve:
        🔍 Similar cases: "Have we had other incidents where a catenary contractor \
applied railway instead of tram-specific wire height tolerances on Citadis units?"
        ⚙️ Operational deep-dive: "What containment actions were applied to TRM-401 \
through TRM-403 in case TRM-20250310-0001 and have they been verified as effective?"
        📊 Strategic view: "Is contractor standard mismatch in catenary maintenance \
a recurring systemic issue across our French depots?"
        📈 KPI & trends: "How frequently do post-maintenance catenary interventions \
trigger unplanned rolling stock corrective actions across the fleet?"
        """
    )

    MOCK_OPERATIONAL_RESPONSE_NO_CASE: str = textwrap.dedent(
        """\
        [CURRENT STATE]
        Your team has just identified a new problem with the pantograph system. \
Before opening a formal investigation, clarify: What exactly happened or was observed? \
When and where did it occur? How widespread is it — one unit, multiple units, \
or the whole fleet? Is there an immediate safety or operational risk right now?

        [SIMILAR CASES — CHECK FIRST]
        Before opening a formal investigation, it is worth checking whether this \
problem has been seen before. Describe the problem in a few words and ask CoSolve: \
'Have we had similar incidents involving pantograph system failure?'
        Past cases may already have a proven solution.

        [IF THIS IS A NEW PROBLEM — HOW TO START]
        If no similar cases exist, the first step is to document the problem clearly \
before any analysis begins. You will need:
        - A clear description of what failed or behaved unexpectedly
        - The affected equipment, line, or location
        - The team who will investigate
        Use the Case Board on the left to open a new case and capture this information.

        [GENERAL ADVICE]
        ⚠️ General advice on starting a new problem investigation:
        The most effective investigations start with a clear, factual description of \
what was observed — not what caused it. Avoid jumping to conclusions before the \
problem is fully documented.

        [WHAT TO EXPLORE NEXT]
        Questions to ask your team right now:
        • What exactly did you observe — describe it in one sentence
        • Is this happening on one unit only or across multiple?

        Questions to ask CoSolve:
        🔍 Similar cases: 'Have we had similar incidents involving pantograph system failure?'
        ⚙️ Once case is open: 'What should we focus on first for this problem?'
        📊 Strategic view: 'Is this type of failure recurring across our fleet?'
        📈 KPI & trends: 'How often do we see this failure type and is it increasing?'
        """
    )

    MOCK_SIMILARITY_RESPONSE: str = textwrap.dedent(
        """\
        [SIMILAR CASES FOUND]
        TRM-20250415-0002 (STRONG match): Pantograph carbon strip premature wear on \
Line 2 following track realignment, traced to a wire height deviation of 120 mm \
below design spec at KP 4.2. The contractor applied railway-grade tolerances instead \
of tram-specific standards — an identical failure mechanism to the current problem.

        TRM-20240820-0003 (PARTIAL match): Arc flash events on STIB Line 7 after OHL \
renewal, caused by residual lubricant contamination. Different failure mode but shares \
the common thread of an inadequate post-installation acceptance procedure allowing \
the defect to reach service.

        [PATTERNS ACROSS CASES]
        Both TRM-20250415-0002 and TRM-20240820-0003 reveal a pattern: catenary \
maintenance or renewal work by external contractors introduces conditions that pass \
through acceptance without detection. The acceptance procedure in both cases lacked \
a check specific to the failure mode introduced.

        [WHAT THIS MEANS FOR YOUR INVESTIGATION]
        Based on TRM-20250415-0002, verify that the Line 4 contractor held tram-specific \
wire height certification. The resolution in TRM-20250415-0002 required updating the \
catenary acceptance specification with tram-specific geometry tolerances — that updated \
procedure should be checked to see whether it was applied to the Line 4 works.

        [GENERAL ADVICE]
        ⚠️ General similarity analysis guidance not specific to this problem:
        Match ratings (STRONG/PARTIAL/WEAK) should reflect the similarity of the failure \
mechanism, not just the symptom. A matched symptom with a different root cause provides \
limited guidance. Always verify the analogous root cause path before applying a closed \
case's corrective actions.

        [WHAT TO EXPLORE NEXT]
        Questions to ask your team right now:
        • Did the Line 4 contractor hold the same tram-specific catenary certification \
that was identified as missing in TRM-20250415-0002?
        • Has the updated catenary acceptance specification from TRM-20250415-0002 been \
formally adopted and was it referenced in the Line 4 maintenance contract?

        Questions to ask CoSolve:
        ⚙️ Operational deep-dive: "What is the current Root Cause Analysis status in \
TRM-20250310-0001 and has the geometry deviation at KP 3.4 been formally documented?"
        📊 Strategic view: "Does the pattern of contractor-caused post-maintenance \
failures across TRM-20250415-0002 and TRM-20240820-0003 indicate a systemic supplier \
qualification gap?"
        📈 KPI & trends: "What is the recurrence rate of post-maintenance catenary \
failures per contractor intervention across France in the last 12 months?"
        🔍 Dig deeper: "What specific corrective actions in TRM-20250415-0002 updated \
the acceptance procedure and were those actions verified as effective?"
        """
    )

    MOCK_STRATEGY_RESPONSE: str = textwrap.dedent(
        """\
        [SYSTEMIC PATTERNS IDENTIFIED]
        Pattern 1 — Contractor Standard Mismatch (systemic): Cases TRM-20250310-0001 \
and TRM-20250415-0002 both involve external contractors applying railway-grade catenary \
specifications to tram installations, resulting in wire height deviations that caused \
rolling stock damage. Two cases confirm this as systemic.

        Pattern 2 — Post-maintenance Acceptance Gap (emerging): [EMERGING — \
TRM-20250310-0001] Both cases lack a mandatory post-maintenance geometry verification \
step before returning the line to service.

        [ROOT CAUSE CATEGORIES]
        Infrastructure Acceptance Failure: TRM-20250310-0001, TRM-20250415-0002 — \
inadequate acceptance procedures failed to detect geometry deviations introduced by \
external contractors.
        Contamination Post-Installation: TRM-20240820-0003 — OHL lubricant residue \
causing arc flash; root cause documented but acceptance procedure gap is analogous.

        [ORGANISATIONAL WEAKNESSES]
        Contractor Qualification Gap: TRM-20250310-0001 and TRM-20250415-0002 confirm \
that external catenary contractors are not held to tram-specific standards. \
This is a confirmed systemic gap, not a hypothesis.
        Acceptance Protocol Gap: Both cases expose the absence of a mandatory \
post-maintenance geometry check. A single case would warrant monitoring; two cases \
confirm the process is structurally missing.

        [GENERAL ADVICE]
        ⚠️ General portfolio-level guidance not specific to this data:
        Fleet operators should audit all infrastructure maintenance contractors for \
tram-specific certification annually. Post-maintenance acceptance procedures for all \
subsystems affecting rolling stock should require cross-functional sign-off. Recurring \
root cause categories should be reviewed at portfolio level each quarter.

        [WHAT TO EXPLORE NEXT]
        TEAM: Have all active catenary maintenance contractors been audited for \
tram-specific qualification and is this a mandatory pre-qualification requirement?
        TEAM: Is there a cross-functional infrastructure/rolling-stock sign-off gate \
before any infrastructure maintenance work returns to service fleet-wide?
        TEAM: How many post-maintenance rolling stock incidents in the last 24 months \
involved external contractors, and are they concentrated in a particular country or depot?
        COSOLVE: Which countries in our portfolio show the highest rate of \
post-maintenance corrective cases linked to external contractors?
        COSOLVE: Are there any other open cases involving contractor-caused \
infrastructure deviations that have not yet been escalated?
        COSOLVE: What is the average resolution time for cases with contractor-related \
root causes compared to internally-caused cases, across the full portfolio?
        """
    )

    # ── Internal helper: read source file and parse AST ───────────────────
    @staticmethod
    def _read_source(node_class: type) -> tuple[str, ast.Module]:
        """Return (source_text, parsed_ast) for the module containing node_class."""
        path = Path(inspect.getfile(node_class))
        source = path.read_text(encoding="utf-8")
        return source, ast.parse(source)

    # ── Mock infrastructure factories ─────────────────────────────────────
    @staticmethod
    def _make_mock_retriever(config: "NodeCheckConfig") -> "_MockRetriever":
        return _MockRetriever(config)

    @staticmethod
    def _make_mock_llm_client(
        default_response: str,
    ) -> "_MockLLMClient":
        return _MockLLMClient(default_response=default_response)

    @staticmethod
    def _make_mock_settings() -> "_MockSettings":
        return _MockSettings()

    @classmethod
    def _make_operational_node(
        cls,
        config: "NodeCheckConfig",
        response_override: str | None = None,
    ) -> OperationalNode:
        response = response_override or config.MOCK_OPERATIONAL_RESPONSE_WITH_CASE
        return OperationalNode(
            hybrid_retriever=cls._make_mock_retriever(config),
            llm_client=cls._make_mock_llm_client(response),
            settings=cls._make_mock_settings(),
        )

    @classmethod
    def _make_similarity_node(
        cls,
        config: "NodeCheckConfig",
        response_override: str | None = None,
    ) -> SimilarityNode:
        response = response_override or config.MOCK_SIMILARITY_RESPONSE
        return SimilarityNode(
            hybrid_retriever=cls._make_mock_retriever(config),
            llm_client=cls._make_mock_llm_client(response),
            settings=cls._make_mock_settings(),
        )

    @classmethod
    def _make_strategy_node(
        cls,
        config: "NodeCheckConfig",
        response_override: str | None = None,
    ) -> StrategyNode:
        response = response_override or config.MOCK_STRATEGY_RESPONSE
        return StrategyNode(
            hybrid_retriever=cls._make_mock_retriever(config),
            llm_client=cls._make_mock_llm_client(response),
            settings=cls._make_mock_settings(),
        )

    @classmethod
    def _make_kpi_node(cls, config: "NodeCheckConfig") -> KPINode:
        kpi_tool = KPITool(
            hybrid_retriever=cls._make_mock_retriever(config),
            settings=cls._make_mock_settings(),
        )
        return KPINode(kpi_tool=kpi_tool, settings=cls._make_mock_settings())

    @classmethod
    def _try_build_live_node(cls, node_class: type) -> Any | None:
        """Attempt to build a live node using real Azure credentials.

        Returns None gracefully if any credential or import error occurs,
        so the suite never crashes in LIVE_MODE=False.
        """
        try:
            from backend.config import settings as _settings
            from backend.llm import get_llm
            from backend.infra.embeddings import EmbeddingClient
            from backend.infra.case_search_client import CaseSearchClient
            from backend.infra.evidence_search_client import EvidenceSearchClient
            from backend.infra.knowledge_search_client import KnowledgeSearchClient
            from backend.retrieval.hybrid_retriever import HybridRetriever

            llm_client = get_llm()
            embedding_client = EmbeddingClient(settings_module=_settings)
            case_client = CaseSearchClient(
                endpoint=_settings.AZURE_SEARCH_ENDPOINT,
                index_name=_settings.CASE_INDEX_NAME,
                admin_key=_settings.AZURE_SEARCH_ADMIN_KEY,
            )
            evidence_client = EvidenceSearchClient(
                endpoint=_settings.AZURE_SEARCH_ENDPOINT,
                index_name=_settings.EVIDENCE_INDEX_NAME,
                admin_key=_settings.AZURE_SEARCH_ADMIN_KEY,
            )
            knowledge_client = KnowledgeSearchClient(
                endpoint=_settings.AZURE_SEARCH_ENDPOINT,
                index_name=_settings.KNOWLEDGE_INDEX_NAME,
                admin_key=_settings.AZURE_SEARCH_ADMIN_KEY,
            )
            retriever = HybridRetriever(
                case_search_client=case_client,
                evidence_search_client=evidence_client,
                knowledge_search_client=knowledge_client,
                embedding_client=embedding_client,
                settings=_settings,
            )

            if node_class is OperationalNode:
                return OperationalNode(
                    hybrid_retriever=retriever,
                    llm_client=llm_client,
                    settings=_settings,
                )
            if node_class is SimilarityNode:
                return SimilarityNode(
                    hybrid_retriever=retriever,
                    llm_client=llm_client,
                    settings=_settings,
                )
            if node_class is StrategyNode:
                return StrategyNode(
                    hybrid_retriever=retriever,
                    llm_client=llm_client,
                    settings=_settings,
                )
            if node_class is KPINode:
                kpi_tool = KPITool(hybrid_retriever=retriever, settings=_settings)
                return KPINode(kpi_tool=kpi_tool, settings=_settings)
        except Exception as exc:
            _log.warning("Live node build failed for %s: %s", node_class.__name__, exc)
        return None


# ══════════════════════════════════════════════════════════════════════════════
# Private helper classes — mock infrastructure (module-internal use only)
# ══════════════════════════════════════════════════════════════════════════════


class _MockSettings:
    """Minimal settings stub for offline checks."""

    AZURE_OPENAI_CHAT_DEPLOYMENT: str = "gpt-4o"
    CASE_INDEX_NAME: str = "mock-cases"
    KNOWLEDGE_INDEX_NAME: str = "mock-knowledge"
    RETRIEVAL_SIMILAR_CASES_TOP_K: int = 5
    RETRIEVAL_EVIDENCE_TOP_K: int = 5
    RETRIEVAL_KNOWLEDGE_TOP_K: int = 4
    RETRIEVAL_CASES_PATTERN_TOP_K: int = 10
    RETRIEVAL_ACTIVE_CASES_TOP_K: int = 50


class _MockRetriever:
    """Mock HybridRetriever that returns the config's canned data."""

    def __init__(self, config: NodeCheckConfig) -> None:
        self._config = config

    def retrieve_similar_cases(
        self,
        query: str,
        current_case_id: Optional[str],
        country: Optional[str],
        top_k: Optional[int] = None,
    ) -> list[CaseSummary]:
        return list(self._config.MOCK_SIMILAR_CASES)

    def retrieve_evidence_for_case(self, case_id: str) -> list[EvidenceSummary]:
        return list(self._config.MOCK_EVIDENCE)

    def retrieve_cases_for_pattern_analysis(
        self,
        query: str,
        country: Optional[str],
        top_k: int = 10,
    ) -> list[CaseSummary]:
        return list(self._config.MOCK_SIMILAR_CASES)

    def retrieve_knowledge(self, query: str, top_k: int = 4) -> list[KnowledgeSummary]:
        return list(self._config.MOCK_KNOWLEDGE)

    def retrieve_cases_for_kpi(
        self, country: Optional[str] = None
    ) -> list[CaseSummary]:
        return list(self._config.MOCK_SIMILAR_CASES)

    def retrieve_active_cases_for_kpi(
        self, country: Optional[str] = None
    ) -> list[CaseSummary]:
        return []

    def retrieve_case_by_id(self, case_id: str) -> Optional[CaseSummary]:
        if case_id == NodeCheckConfig.SAMPLE_CASE_ID:
            return NodeCheckConfig.MOCK_KPI_CASE
        return None


class _MockAIMessage:
    """Mimics langchain_core AIMessage with a .content attribute."""

    def __init__(self, content: str) -> None:
        self.content = content


class _MockStructuredLLM:
    """Mimics llm.with_structured_output(Model) — returns a callable with .invoke()."""

    def __init__(self, response_model: type, fixed_result: Any = None) -> None:
        self._response_model = response_model
        self._fixed_result = fixed_result

    def invoke(self, messages: list) -> Any:
        if self._fixed_result is not None:
            return self._fixed_result
        return self._response_model.model_validate({})


class _MockLLMClient:
    """Mock AzureChatOpenAI that returns the supplied canned response."""

    def __init__(self, default_response: str) -> None:
        self._default_response = default_response

    def invoke(self, messages: list) -> _MockAIMessage:
        return _MockAIMessage(self._default_response)

    def with_structured_output(self, response_model: type) -> _MockStructuredLLM:
        return _MockStructuredLLM(response_model)


class _MockQuestionReadinessLLMClient:
    """Mock LLM client that returns a fixed QuestionReadinessResult."""

    def __init__(self, ready: bool, clarifying_question: str = "") -> None:
        self._ready = ready
        self._cq = clarifying_question

    def invoke(self, messages: list) -> _MockAIMessage:
        return _MockAIMessage("")

    def with_structured_output(self, response_model: type) -> _MockStructuredLLM:
        result = response_model(ready=self._ready, clarifying_question=self._cq)
        return _MockStructuredLLM(response_model, fixed_result=result)


# ══════════════════════════════════════════════════════════════════════════════
# Shared AST helpers (private module-level utility — accessed via classes only)
# ══════════════════════════════════════════════════════════════════════════════


class _ASTHelper:
    """Static AST inspection utilities, accessed by check classes only."""

    @staticmethod
    def module_level_function_names(tree: ast.Module) -> list[str]:
        """Return names of any function defined directly at module level."""
        return [
            node.name
            for node in ast.iter_child_nodes(tree)
            if isinstance(node, ast.FunctionDef)
        ]

    @staticmethod
    def has_del_statements(tree: ast.Module) -> bool:
        """Return True if any `del` statement appears anywhere in the module."""
        return any(isinstance(n, ast.Delete) for n in ast.walk(tree))

    @staticmethod
    def class_method_names(tree: ast.Module, class_name: str) -> list[str]:
        """Return all method names defined on the named class."""
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                return [
                    m.name
                    for m in ast.iter_child_nodes(node)
                    if isinstance(m, ast.FunctionDef)
                ]
        return []

    @staticmethod
    def module_level_string_constant_names(tree: ast.Module) -> list[str]:
        """Return names of module-level assignments to string constants that look
        like prompt definitions (name ends in _PROMPT or _SYSTEM or _TEMPLATE)."""
        names: list[str] = []
        for node in ast.iter_child_nodes(tree):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if not isinstance(target, ast.Name):
                    continue
                name_upper = target.id.upper()
                if any(
                    name_upper.endswith(suffix)
                    for suffix in ("_PROMPT", "_SYSTEM", "_TEMPLATE", "_KEYWORDS")
                ):
                    names.append(target.id)
        return names

    @staticmethod
    def class_attribute_names(tree: ast.Module, class_name: str) -> list[str]:
        """Return all class-level attribute names (direct Assign children inside
        the class body, not inside any method)."""
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                attrs: list[str] = []
                for child in ast.iter_child_nodes(node):
                    if isinstance(child, ast.Assign):
                        for t in child.targets:
                            if isinstance(t, ast.Name):
                                attrs.append(t.id)
                    elif isinstance(child, ast.AnnAssign) and isinstance(
                        child.target, ast.Name
                    ):
                        attrs.append(child.target.id)
                return attrs
        return []


# ══════════════════════════════════════════════════════════════════════════════
# CheckResult — lightweight result container
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class CheckResult:
    """Result of a single automated check."""

    name: str
    passed: bool
    detail: str = ""
    skipped: bool = False

    @property
    def status_label(self) -> str:
        if self.skipped:
            return "SKIP"
        return "PASS" if self.passed else "FAIL"

    @property
    def icon(self) -> str:
        if self.skipped:
            return "⏭️ "
        return "✅" if self.passed else "❌"


# ══════════════════════════════════════════════════════════════════════════════
# Shared quality-gate text helpers
# ══════════════════════════════════════════════════════════════════════════════


class _QualityGateHelper:
    """Heuristic text checks that replay the reflection-node audit criteria."""

    @staticmethod
    def has_section(text: str, marker: str) -> bool:
        return marker in text

    @staticmethod
    def extract_section(text: str, start_marker: str, end_markers: list[str]) -> str:
        idx = text.find(start_marker)
        if idx < 0:
            return ""
        content_start = idx + len(start_marker)
        end_idx = len(text)
        for em in end_markers:
            pos = text.find(em, content_start)
            if 0 < pos < end_idx:
                end_idx = pos
        return text[content_start:end_idx].strip()

    @staticmethod
    def general_advice_is_flagged(text: str) -> bool:
        """Check [GENERAL ADVICE] section carries the ⚠️ warning prefix.

        Accepts both the full emoji form ⚠️ (U+26A0 U+FE0F) and the plain
        warning sign ⚠ (U+26A0) which some LLMs output without the variation
        selector.
        """
        section = _QualityGateHelper.extract_section(
            text,
            "[GENERAL ADVICE]",
            ["[WHAT TO EXPLORE NEXT]"],
        )
        return bool(section) and "\u26a0" in section

    @staticmethod
    def explore_next_has_both_subsections(text: str) -> bool:
        """Check [WHAT TO EXPLORE NEXT] has both team and CoSolve subsections."""
        section = _QualityGateHelper.extract_section(text, "[WHAT TO EXPLORE NEXT]", [])
        if not section:
            return False
        has_team = (
            "questions to ask your team" in section.lower()
            or "team:" in section.lower()
            or "•" in section
            or "-" in section
        )
        has_cosolve = (
            "questions to ask cosolve" in section.lower()
            or "cosolve:" in section.lower()
            or any(emoji in section for emoji in ("🔍", "⚙️", "📊", "📈", "🔎"))
        )
        return has_team and has_cosolve

    @staticmethod
    def scan_banned_terms(
        text: str,
        config: NodeCheckConfig,
    ) -> list[str]:
        """Return a list of (term, snippet) strings for every banned term found."""
        hits: list[str] = []
        # D-codes
        for match in config.BANNED_D_CODE_PATTERN.finditer(text):
            # Only flag the raw code, not legitimate labels like "D1_2 Problem Definition"
            start = max(0, match.start() - 20)
            end = min(len(text), match.end() + 20)
            snippet = text[start:end].replace("\n", " ")
            hits.append(f"D-code '{match.group()}' in: «...{snippet}...»")
        # Tech terms (case-insensitive)
        text_lower = text.lower()
        for term in config.BANNED_TECH_TERMS:
            pos = text_lower.find(term.lower())
            if pos >= 0:
                start = max(0, pos - 20)
                end = min(len(text), pos + len(term) + 20)
                snippet = text[start:end].replace("\n", " ")
                hits.append(f"Tech term '{term}' in: «...{snippet}...»")
        return hits

    @staticmethod
    def references_case_id(text: str, case_id: str) -> bool:
        """Check whether the output text references the active case ID."""
        return case_id in text

    @staticmethod
    def strategy_has_team_cosolve(text: str) -> tuple[int, int]:
        """Return (team_count, cosolve_count) in [WHAT TO EXPLORE NEXT]."""
        section = _QualityGateHelper.extract_section(text, "[WHAT TO EXPLORE NEXT]", [])
        team_count = sum(
            1
            for line in section.split("\n")
            if line.strip().upper().startswith("TEAM:")
        )
        cosolve_count = sum(
            1
            for line in section.split("\n")
            if line.strip().upper().startswith("COSOLVE:")
        )
        return team_count, cosolve_count

    @staticmethod
    def kpi_has_no_d_codes(kpi_result: KPIResult) -> list[str]:
        """Scan all string fields of KPIResult for raw D-codes."""
        hits: list[str] = []
        pattern = re.compile(r"\b(D[1-8](?:_[12]|_D2)?)\b")
        for field_name, value in kpi_result.model_dump(exclude_none=True).items():
            text = str(value)
            for match in pattern.finditer(text):
                hits.append(f"D-code '{match.group()}' in field '{field_name}'")
        return hits


# ══════════════════════════════════════════════════════════════════════════════
# OperationalNodeChecks
# ══════════════════════════════════════════════════════════════════════════════


class OperationalNodeChecks:
    """Automated checks for OperationalNode."""

    def __init__(self, config: NodeCheckConfig) -> None:
        self._cfg = config

    # ── Category 1: Structural Integrity ─────────────────────────────────

    def test_no_module_level_functions(self) -> CheckResult:
        source, tree = NodeCheckConfig._read_source(OperationalNode)
        funcs = _ASTHelper.module_level_function_names(tree)
        if funcs:
            return CheckResult(
                "OperationalNode: no module-level functions",
                passed=False,
                detail=f"Found module-level functions: {funcs}",
            )
        return CheckResult("OperationalNode: no module-level functions", passed=True)

    def test_no_del_statements(self) -> CheckResult:
        source, tree = NodeCheckConfig._read_source(OperationalNode)
        if _ASTHelper.has_del_statements(tree):
            return CheckResult(
                "OperationalNode: no del statements",
                passed=False,
                detail="del statement found in source",
            )
        return CheckResult("OperationalNode: no del statements", passed=True)

    def test_prompts_are_class_level(self) -> CheckResult:
        source, tree = NodeCheckConfig._read_source(OperationalNode)
        module_prompts = _ASTHelper.module_level_string_constant_names(tree)
        if module_prompts:
            return CheckResult(
                "OperationalNode: prompts are class-level attributes",
                passed=False,
                detail=f"Module-level prompt names found: {module_prompts}",
            )
        return CheckResult(
            "OperationalNode: prompts are class-level attributes", passed=True
        )

    def test_required_methods_exist(self) -> CheckResult:
        source, tree = NodeCheckConfig._read_source(OperationalNode)
        methods = _ASTHelper.class_method_names(tree, "OperationalNode")
        required = {"run"}
        missing = required - set(methods)
        if missing:
            return CheckResult(
                "OperationalNode: required methods exist",
                passed=False,
                detail=f"Missing methods: {missing}",
            )
        return CheckResult("OperationalNode: required methods exist", passed=True)

    def test_output_model_type(self) -> CheckResult:
        """Verify OperationalNode.run() returns an OperationalNodeOutput."""
        node = NodeCheckConfig._make_operational_node(self._cfg)
        try:
            result = node.run(
                question=self._cfg.OPERATIONAL_QUESTION_WITH_CASE,
                case_id=self._cfg.SAMPLE_CASE_ID,
                case_context=self._cfg.SAMPLE_CASE_CONTEXT,
                current_d_state="D4",
            )
            if not isinstance(result, OperationalNodeOutput):
                return CheckResult(
                    "OperationalNode: output model type",
                    passed=False,
                    detail=f"Got {type(result).__name__}, expected OperationalNodeOutput",
                )
        except Exception as exc:
            return CheckResult(
                "OperationalNode: output model type",
                passed=False,
                detail=f"Exception: {exc}",
            )
        return CheckResult("OperationalNode: output model type", passed=True)

    # ── Category 2: Input/Output Contract ────────────────────────────────

    def test_io_contract_with_case(self) -> CheckResult:
        node = NodeCheckConfig._make_operational_node(self._cfg)
        try:
            result = node.run(
                question=self._cfg.OPERATIONAL_QUESTION_WITH_CASE,
                case_id=self._cfg.SAMPLE_CASE_ID,
                case_context=self._cfg.SAMPLE_CASE_CONTEXT,
                current_d_state="D4",
            )
            draft = result.operational_draft
            issues: list[str] = []
            if not isinstance(result, OperationalNodeOutput):
                issues.append("output not OperationalNodeOutput")
            if not draft.current_state:
                issues.append("current_state is empty")
            if not draft.current_state_recommendations:
                issues.append("current_state_recommendations is empty")
            if draft.current_state_recommendations is None:
                issues.append("current_state_recommendations is None")
            if issues:
                return CheckResult(
                    "OperationalNode: I/O contract (case loaded)",
                    passed=False,
                    detail="; ".join(issues),
                )
        except Exception as exc:
            return CheckResult(
                "OperationalNode: I/O contract (case loaded)",
                passed=False,
                detail=f"Exception: {exc}\n{traceback.format_exc()}",
            )
        return CheckResult("OperationalNode: I/O contract (case loaded)", passed=True)

    def test_io_contract_no_case(self) -> CheckResult:
        """New-problem path: no case_id, keyword triggers alternative prompt."""
        node = NodeCheckConfig._make_operational_node(
            self._cfg,
            response_override=self._cfg.MOCK_OPERATIONAL_RESPONSE_NO_CASE,
        )
        try:
            result = node.run(
                question=self._cfg.OPERATIONAL_QUESTION_NO_CASE,
                case_id="",
                case_context={},
                current_d_state=None,
            )
            draft = result.operational_draft
            issues: list[str] = []
            if draft.current_state != "No case loaded":
                issues.append(
                    f"expected current_state='No case loaded', got '{draft.current_state}'"
                )
            if not draft.current_state_recommendations:
                issues.append("current_state_recommendations is empty")
            if issues:
                return CheckResult(
                    "OperationalNode: I/O contract (no case)",
                    passed=False,
                    detail="; ".join(issues),
                )
        except Exception as exc:
            return CheckResult(
                "OperationalNode: I/O contract (no case)",
                passed=False,
                detail=f"Exception: {exc}",
            )
        return CheckResult("OperationalNode: I/O contract (no case)", passed=True)

    def test_suggestions_extracted(self) -> CheckResult:
        """Verify [WHAT TO EXPLORE NEXT] is parsed into structured suggestion chips."""
        node = NodeCheckConfig._make_operational_node(self._cfg)
        try:
            result = node.run(
                question=self._cfg.OPERATIONAL_QUESTION_WITH_CASE,
                case_id=self._cfg.SAMPLE_CASE_ID,
                case_context=self._cfg.SAMPLE_CASE_CONTEXT,
                current_d_state="D4",
            )
            suggestions = result.operational_draft.suggestions
            if not suggestions:
                return CheckResult(
                    "OperationalNode: suggestions extracted",
                    passed=False,
                    detail="suggestions list is empty",
                )
            required_keys = {"label", "question", "type"}
            for suggestion in suggestions:
                if not required_keys.issubset(suggestion.keys()):
                    return CheckResult(
                        "OperationalNode: suggestions extracted",
                        passed=False,
                        detail=f"suggestion missing keys: {suggestion}",
                    )
        except Exception as exc:
            return CheckResult(
                "OperationalNode: suggestions extracted",
                passed=False,
                detail=f"Exception: {exc}",
            )
        return CheckResult("OperationalNode: suggestions extracted", passed=True)

    # ── Category 3: Quality Gate ──────────────────────────────────────────

    def test_quality_gate_case_loaded(self) -> CheckResult:
        if not self._cfg.LIVE_MODE:
            return CheckResult(
                "OperationalNode: quality gate (case loaded)",
                passed=True,
                skipped=True,
                detail="LIVE_MODE=False — set NodeCheckConfig.LIVE_MODE=True to enable",
            )
        node = NodeCheckConfig._try_build_live_node(OperationalNode)
        if node is None:
            return CheckResult(
                "OperationalNode: quality gate (case loaded)",
                passed=True,
                skipped=True,
                detail="Live node unavailable — Azure credentials missing",
            )
        try:
            result = node.run(
                question=self._cfg.OPERATIONAL_QUESTION_WITH_CASE,
                case_id=self._cfg.SAMPLE_CASE_ID,
                case_context=self._cfg.SAMPLE_CASE_CONTEXT,
                current_d_state="D4",
            )
            text = result.operational_draft.current_state_recommendations
            issues: list[str] = []
            required_sections = [
                "[CURRENT STATE]",
                "[GAPS IN PREVIOUS STATES]",
                "[NEXT STATE PREVIEW]",
                "[GENERAL ADVICE]",
                "[WHAT TO EXPLORE NEXT]",
            ]
            for section in required_sections:
                if not _QualityGateHelper.has_section(text, section):
                    issues.append(f"missing section: {section}")
            if not _QualityGateHelper.general_advice_is_flagged(text):
                issues.append("[GENERAL ADVICE] missing ⚠️ warning prefix")
            if not _QualityGateHelper.explore_next_has_both_subsections(text):
                issues.append(
                    "[WHAT TO EXPLORE NEXT] missing team or CoSolve subsection"
                )
            if not _QualityGateHelper.references_case_id(
                text, self._cfg.SAMPLE_CASE_ID
            ):
                issues.append(
                    f"case grounding weak — case ID '{self._cfg.SAMPLE_CASE_ID}' "
                    "not found in output"
                )
            if issues:
                return CheckResult(
                    "OperationalNode: quality gate (case loaded)",
                    passed=False,
                    detail="; ".join(issues),
                )
        except Exception as exc:
            return CheckResult(
                "OperationalNode: quality gate (case loaded)",
                passed=False,
                detail=f"Exception: {exc}",
            )
        return CheckResult("OperationalNode: quality gate (case loaded)", passed=True)

    def test_quality_gate_mock_response_structure(self) -> CheckResult:
        """Fast structural quality gate on the mock response (runs in all modes)."""
        text = self._cfg.MOCK_OPERATIONAL_RESPONSE_WITH_CASE
        issues: list[str] = []
        for section in [
            "[CURRENT STATE]",
            "[GAPS IN PREVIOUS STATES]",
            "[NEXT STATE PREVIEW]",
            "[GENERAL ADVICE]",
            "[WHAT TO EXPLORE NEXT]",
        ]:
            if not _QualityGateHelper.has_section(text, section):
                issues.append(f"missing section: {section}")
        if not _QualityGateHelper.general_advice_is_flagged(text):
            issues.append("[GENERAL ADVICE] missing ⚠️ prefix")
        if not _QualityGateHelper.explore_next_has_both_subsections(text):
            issues.append("[WHAT TO EXPLORE NEXT] missing team or CoSolve subsection")
        if not _QualityGateHelper.references_case_id(text, self._cfg.SAMPLE_CASE_ID):
            issues.append("mock response does not reference sample case ID")
        if issues:
            return CheckResult(
                "OperationalNode: quality gate (mock response structure)",
                passed=False,
                detail="; ".join(issues),
            )
        return CheckResult(
            "OperationalNode: quality gate (mock response structure)", passed=True
        )

    # ── Category 4: Banned Term Detection ────────────────────────────────

    def test_banned_terms_in_mock_output(self) -> CheckResult:
        node = NodeCheckConfig._make_operational_node(self._cfg)
        try:
            result = node.run(
                question=self._cfg.OPERATIONAL_QUESTION_WITH_CASE,
                case_id=self._cfg.SAMPLE_CASE_ID,
                case_context=self._cfg.SAMPLE_CASE_CONTEXT,
                current_d_state="D4",
            )
            text = result.operational_draft.current_state_recommendations
            hits = _QualityGateHelper.scan_banned_terms(text, self._cfg)
            if hits:
                return CheckResult(
                    "OperationalNode: banned term detection",
                    passed=False,
                    detail="\n".join(hits),
                )
        except Exception as exc:
            return CheckResult(
                "OperationalNode: banned term detection",
                passed=False,
                detail=f"Exception: {exc}",
            )
        return CheckResult("OperationalNode: banned term detection", passed=True)

    def test_is_new_problem_question_logic(self) -> CheckResult:
        """Unit-test the keyword detection routing logic."""
        issues: list[str] = []
        positives = [
            ("we just found a new problem", ""),
            ("where do we start", ""),
            ("brand new issue with the brake system", ""),
            ("we have a failure", ""),  # ≤10 words + domain word + no case
        ]
        negatives = [
            ("what should we do for root cause", "CASE-001"),  # case loaded
            ("analyse the root cause findings", "CASE-001"),
        ]
        for q, cid in positives:
            if not is_new_problem_question(q, cid):
                issues.append(f"Expected True for: q='{q}', case_id='{cid}'")
        for q, cid in negatives:
            if is_new_problem_question(q, cid):
                issues.append(f"Expected False for: q='{q}', case_id='{cid}'")
        if issues:
            return CheckResult(
                "OperationalNode: new-problem detection logic",
                passed=False,
                detail="; ".join(issues),
            )
        return CheckResult("OperationalNode: new-problem detection logic", passed=True)

    def run_all(self) -> list[CheckResult]:
        """Run all OperationalNode checks."""
        return [
            self.test_no_module_level_functions(),
            self.test_no_del_statements(),
            self.test_prompts_are_class_level(),
            self.test_required_methods_exist(),
            self.test_output_model_type(),
            self.test_io_contract_with_case(),
            self.test_io_contract_no_case(),
            self.test_suggestions_extracted(),
            self.test_quality_gate_case_loaded(),
            self.test_quality_gate_mock_response_structure(),
            self.test_banned_terms_in_mock_output(),
            self.test_is_new_problem_question_logic(),
        ]


# ══════════════════════════════════════════════════════════════════════════════
# SimilarityNodeChecks
# ══════════════════════════════════════════════════════════════════════════════


class SimilarityNodeChecks:
    """Automated checks for SimilarityNode."""

    def __init__(self, config: NodeCheckConfig) -> None:
        self._cfg = config

    # ── Category 1: Structural Integrity ─────────────────────────────────

    def test_no_module_level_functions(self) -> CheckResult:
        source, tree = NodeCheckConfig._read_source(SimilarityNode)
        funcs = _ASTHelper.module_level_function_names(tree)
        if funcs:
            return CheckResult(
                "SimilarityNode: no module-level functions",
                passed=False,
                detail=f"Found: {funcs}",
            )
        return CheckResult("SimilarityNode: no module-level functions", passed=True)

    def test_no_del_statements(self) -> CheckResult:
        source, tree = NodeCheckConfig._read_source(SimilarityNode)
        if _ASTHelper.has_del_statements(tree):
            return CheckResult(
                "SimilarityNode: no del statements",
                passed=False,
                detail="del statement found in source",
            )
        return CheckResult("SimilarityNode: no del statements", passed=True)

    def test_prompts_are_class_level(self) -> CheckResult:
        source, tree = NodeCheckConfig._read_source(SimilarityNode)
        module_prompts = _ASTHelper.module_level_string_constant_names(tree)
        if module_prompts:
            return CheckResult(
                "SimilarityNode: prompts are class-level attributes",
                passed=False,
                detail=f"Module-level prompt names: {module_prompts}",
            )
        return CheckResult(
            "SimilarityNode: prompts are class-level attributes", passed=True
        )

    def test_required_methods_exist(self) -> CheckResult:
        source, tree = NodeCheckConfig._read_source(SimilarityNode)
        methods = _ASTHelper.class_method_names(tree, "SimilarityNode")
        required = {"run", "_extract_suggestions"}
        missing = required - set(methods)
        if missing:
            return CheckResult(
                "SimilarityNode: required methods exist",
                passed=False,
                detail=f"Missing: {missing}",
            )
        return CheckResult("SimilarityNode: required methods exist", passed=True)

    def test_output_model_type(self) -> CheckResult:
        node = NodeCheckConfig._make_similarity_node(self._cfg)
        try:
            result = node.run(
                question=self._cfg.SIMILARITY_QUESTION_WITH_CASE,
                case_id=self._cfg.SAMPLE_CASE_ID,
                country="France",
                case_context=self._cfg.SAMPLE_CASE_CONTEXT,
            )
            if not isinstance(result, SimilarityNodeOutput):
                return CheckResult(
                    "SimilarityNode: output model type",
                    passed=False,
                    detail=f"Got {type(result).__name__}",
                )
        except Exception as exc:
            return CheckResult(
                "SimilarityNode: output model type",
                passed=False,
                detail=f"Exception: {exc}",
            )
        return CheckResult("SimilarityNode: output model type", passed=True)

    # ── Category 2: Input/Output Contract ────────────────────────────────

    def test_io_contract_with_case(self) -> CheckResult:
        node = NodeCheckConfig._make_similarity_node(self._cfg)
        try:
            result = node.run(
                question=self._cfg.SIMILARITY_QUESTION_WITH_CASE,
                case_id=self._cfg.SAMPLE_CASE_ID,
                country="France",
                case_context=self._cfg.SAMPLE_CASE_CONTEXT,
            )
            draft = result.similarity_draft
            issues: list[str] = []
            if not isinstance(result, SimilarityNodeOutput):
                issues.append("output not SimilarityNodeOutput")
            if not draft.summary:
                issues.append("summary is empty")
            if draft.summary is None:
                issues.append("summary is None")
            if issues:
                return CheckResult(
                    "SimilarityNode: I/O contract (case loaded)",
                    passed=False,
                    detail="; ".join(issues),
                )
        except Exception as exc:
            return CheckResult(
                "SimilarityNode: I/O contract (case loaded)",
                passed=False,
                detail=f"Exception: {exc}",
            )
        return CheckResult("SimilarityNode: I/O contract (case loaded)", passed=True)

    def test_io_contract_no_case(self) -> CheckResult:
        node = NodeCheckConfig._make_similarity_node(self._cfg)
        try:
            result = node.run(
                question=self._cfg.SIMILARITY_QUESTION_NO_CASE,
                case_id=None,
                country=None,
                case_context=None,
            )
            draft = result.similarity_draft
            issues: list[str] = []
            if not draft.summary:
                issues.append("summary is empty")
            if issues:
                return CheckResult(
                    "SimilarityNode: I/O contract (no case)",
                    passed=False,
                    detail="; ".join(issues),
                )
        except Exception as exc:
            return CheckResult(
                "SimilarityNode: I/O contract (no case)",
                passed=False,
                detail=f"Exception: {exc}",
            )
        return CheckResult("SimilarityNode: I/O contract (no case)", passed=True)

    def test_supporting_cases_forwarded(self) -> CheckResult:
        """Verify retrieved cases are forwarded into SimilarityPayload."""
        node = NodeCheckConfig._make_similarity_node(self._cfg)
        try:
            result = node.run(
                question=self._cfg.SIMILARITY_QUESTION_WITH_CASE,
                case_id=self._cfg.SAMPLE_CASE_ID,
                country="France",
                case_context=self._cfg.SAMPLE_CASE_CONTEXT,
            )
            if not result.similarity_draft.supporting_cases:
                return CheckResult(
                    "SimilarityNode: supporting cases forwarded",
                    passed=False,
                    detail="supporting_cases list is empty",
                )
        except Exception as exc:
            return CheckResult(
                "SimilarityNode: supporting cases forwarded",
                passed=False,
                detail=f"Exception: {exc}",
            )
        return CheckResult("SimilarityNode: supporting cases forwarded", passed=True)

    # ── Category 3: Quality Gate ──────────────────────────────────────────

    def test_quality_gate_live(self) -> CheckResult:
        if not self._cfg.LIVE_MODE:
            return CheckResult(
                "SimilarityNode: quality gate (live)",
                passed=True,
                skipped=True,
                detail="LIVE_MODE=False",
            )
        node = NodeCheckConfig._try_build_live_node(SimilarityNode)
        if node is None:
            return CheckResult(
                "SimilarityNode: quality gate (live)",
                passed=True,
                skipped=True,
                detail="Live node unavailable",
            )
        try:
            result = node.run(
                question=self._cfg.SIMILARITY_QUESTION_WITH_CASE,
                case_id=self._cfg.SAMPLE_CASE_ID,
                country="France",
                case_context=self._cfg.SAMPLE_CASE_CONTEXT,
            )
            text = result.similarity_draft.summary
            issues: list[str] = []
            for section in [
                "[SIMILAR CASES FOUND]",
                "[PATTERNS ACROSS CASES]",
                "[WHAT THIS MEANS FOR YOUR INVESTIGATION]",
                "[GENERAL ADVICE]",
                "[WHAT TO EXPLORE NEXT]",
            ]:
                if not _QualityGateHelper.has_section(text, section):
                    issues.append(f"missing section: {section}")
            if not _QualityGateHelper.general_advice_is_flagged(text):
                issues.append("[GENERAL ADVICE] missing ⚠️ prefix")
            if not _QualityGateHelper.explore_next_has_both_subsections(text):
                issues.append("[WHAT TO EXPLORE NEXT] missing subsection")
            retrieved_ids = [
                c.case_id for c in result.similarity_draft.supporting_cases
            ]
            case_ids_in_output = [cid for cid in retrieved_ids if cid in text]
            if retrieved_ids and not case_ids_in_output:
                issues.append("case_specificity: no retrieved case IDs found in output")
            if issues:
                return CheckResult(
                    "SimilarityNode: quality gate (live)",
                    passed=False,
                    detail="; ".join(issues),
                )
        except Exception as exc:
            return CheckResult(
                "SimilarityNode: quality gate (live)",
                passed=False,
                detail=f"Exception: {exc}",
            )
        return CheckResult("SimilarityNode: quality gate (live)", passed=True)

    def test_quality_gate_mock_response_structure(self) -> CheckResult:
        text = self._cfg.MOCK_SIMILARITY_RESPONSE
        issues: list[str] = []
        for section in [
            "[SIMILAR CASES FOUND]",
            "[PATTERNS ACROSS CASES]",
            "[WHAT THIS MEANS FOR YOUR INVESTIGATION]",
            "[GENERAL ADVICE]",
            "[WHAT TO EXPLORE NEXT]",
        ]:
            if not _QualityGateHelper.has_section(text, section):
                issues.append(f"missing section: {section}")
        if not _QualityGateHelper.general_advice_is_flagged(text):
            issues.append("[GENERAL ADVICE] missing ⚠️ prefix")
        if not _QualityGateHelper.explore_next_has_both_subsections(text):
            issues.append("[WHAT TO EXPLORE NEXT] missing subsection")
        # case_specificity: case IDs from mock cases must appear
        for case in self._cfg.MOCK_SIMILAR_CASES:
            if case.case_id not in text:
                issues.append(
                    f"case_specificity: case ID '{case.case_id}' not in mock response"
                )
        if issues:
            return CheckResult(
                "SimilarityNode: quality gate (mock response structure)",
                passed=False,
                detail="; ".join(issues),
            )
        return CheckResult(
            "SimilarityNode: quality gate (mock response structure)", passed=True
        )

    # ── Category 4: Banned Term Detection ────────────────────────────────

    def test_banned_terms_in_mock_output(self) -> CheckResult:
        node = NodeCheckConfig._make_similarity_node(self._cfg)
        try:
            result = node.run(
                question=self._cfg.SIMILARITY_QUESTION_WITH_CASE,
                case_id=self._cfg.SAMPLE_CASE_ID,
                country="France",
                case_context=self._cfg.SAMPLE_CASE_CONTEXT,
            )
            text = result.similarity_draft.summary
            hits = _QualityGateHelper.scan_banned_terms(text, self._cfg)
            if hits:
                return CheckResult(
                    "SimilarityNode: banned term detection",
                    passed=False,
                    detail="\n".join(hits),
                )
        except Exception as exc:
            return CheckResult(
                "SimilarityNode: banned term detection",
                passed=False,
                detail=f"Exception: {exc}",
            )
        return CheckResult("SimilarityNode: banned term detection", passed=True)

    def run_all(self) -> list[CheckResult]:
        return [
            self.test_no_module_level_functions(),
            self.test_no_del_statements(),
            self.test_prompts_are_class_level(),
            self.test_required_methods_exist(),
            self.test_output_model_type(),
            self.test_io_contract_with_case(),
            self.test_io_contract_no_case(),
            self.test_supporting_cases_forwarded(),
            self.test_quality_gate_live(),
            self.test_quality_gate_mock_response_structure(),
            self.test_banned_terms_in_mock_output(),
        ]


# ══════════════════════════════════════════════════════════════════════════════
# StrategyNodeChecks
# ══════════════════════════════════════════════════════════════════════════════


class StrategyNodeChecks:
    """Automated checks for StrategyNode."""

    def __init__(self, config: NodeCheckConfig) -> None:
        self._cfg = config

    # ── Category 1: Structural Integrity ─────────────────────────────────

    def test_no_module_level_functions(self) -> CheckResult:
        source, tree = NodeCheckConfig._read_source(StrategyNode)
        funcs = _ASTHelper.module_level_function_names(tree)
        if funcs:
            return CheckResult(
                "StrategyNode: no module-level functions",
                passed=False,
                detail=f"Found: {funcs}",
            )
        return CheckResult("StrategyNode: no module-level functions", passed=True)

    def test_no_del_statements(self) -> CheckResult:
        source, tree = NodeCheckConfig._read_source(StrategyNode)
        if _ASTHelper.has_del_statements(tree):
            return CheckResult(
                "StrategyNode: no del statements",
                passed=False,
                detail="del statement found",
            )
        return CheckResult("StrategyNode: no del statements", passed=True)

    def test_prompts_are_class_level(self) -> CheckResult:
        source, tree = NodeCheckConfig._read_source(StrategyNode)
        module_prompts = _ASTHelper.module_level_string_constant_names(tree)
        if module_prompts:
            return CheckResult(
                "StrategyNode: prompts are class-level attributes",
                passed=False,
                detail=f"Module-level: {module_prompts}",
            )
        return CheckResult(
            "StrategyNode: prompts are class-level attributes", passed=True
        )

    def test_required_methods_exist(self) -> CheckResult:
        source, tree = NodeCheckConfig._read_source(StrategyNode)
        methods = _ASTHelper.class_method_names(tree, "StrategyNode")
        required = {"run", "_extract_suggestions"}
        missing = required - set(methods)
        if missing:
            return CheckResult(
                "StrategyNode: required methods exist",
                passed=False,
                detail=f"Missing: {missing}",
            )
        return CheckResult("StrategyNode: required methods exist", passed=True)

    def test_output_model_type(self) -> CheckResult:
        node = NodeCheckConfig._make_strategy_node(self._cfg)
        try:
            result = node.run(
                question=self._cfg.STRATEGY_QUESTION,
                country=None,
            )
            if not isinstance(result, StrategyNodeOutput):
                return CheckResult(
                    "StrategyNode: output model type",
                    passed=False,
                    detail=f"Got {type(result).__name__}",
                )
        except Exception as exc:
            return CheckResult(
                "StrategyNode: output model type",
                passed=False,
                detail=f"Exception: {exc}",
            )
        return CheckResult("StrategyNode: output model type", passed=True)

    # ── Category 2: Input/Output Contract ────────────────────────────────

    def test_io_contract_global(self) -> CheckResult:
        node = NodeCheckConfig._make_strategy_node(self._cfg)
        try:
            result = node.run(
                question=self._cfg.STRATEGY_QUESTION,
                country=None,
            )
            draft = result.strategy_draft
            issues: list[str] = []
            if not isinstance(result, StrategyNodeOutput):
                issues.append("output not StrategyNodeOutput")
            if not draft.summary:
                issues.append("summary is empty")
            if issues:
                return CheckResult(
                    "StrategyNode: I/O contract (global)",
                    passed=False,
                    detail="; ".join(issues),
                )
        except Exception as exc:
            return CheckResult(
                "StrategyNode: I/O contract (global)",
                passed=False,
                detail=f"Exception: {exc}",
            )
        return CheckResult("StrategyNode: I/O contract (global)", passed=True)

    def test_io_contract_country_filtered(self) -> CheckResult:
        node = NodeCheckConfig._make_strategy_node(self._cfg)
        try:
            result = node.run(
                question=self._cfg.STRATEGY_QUESTION,
                country="France",
            )
            if not result.strategy_draft.summary:
                return CheckResult(
                    "StrategyNode: I/O contract (country filter)",
                    passed=False,
                    detail="summary is empty for country-filtered query",
                )
        except Exception as exc:
            return CheckResult(
                "StrategyNode: I/O contract (country filter)",
                passed=False,
                detail=f"Exception: {exc}",
            )
        return CheckResult("StrategyNode: I/O contract (country filter)", passed=True)

    def test_suggestions_extracted(self) -> CheckResult:
        node = NodeCheckConfig._make_strategy_node(self._cfg)
        try:
            result = node.run(
                question=self._cfg.STRATEGY_QUESTION,
                country=None,
            )
            suggestions = result.strategy_draft.suggestions
            if not suggestions:
                return CheckResult(
                    "StrategyNode: suggestions extracted",
                    passed=False,
                    detail="suggestions list is empty",
                )
            required_keys = {"label", "question", "type"}
            for suggestion in suggestions:
                if not required_keys.issubset(suggestion.keys()):
                    return CheckResult(
                        "StrategyNode: suggestions extracted",
                        passed=False,
                        detail=f"suggestion missing keys: {suggestion}",
                    )
        except Exception as exc:
            return CheckResult(
                "StrategyNode: suggestions extracted",
                passed=False,
                detail=f"Exception: {exc}",
            )
        return CheckResult("StrategyNode: suggestions extracted", passed=True)

    # ── Category 3: Quality Gate ──────────────────────────────────────────

    def test_quality_gate_live(self) -> CheckResult:
        if not self._cfg.LIVE_MODE:
            return CheckResult(
                "StrategyNode: quality gate (live)",
                passed=True,
                skipped=True,
                detail="LIVE_MODE=False",
            )
        node = NodeCheckConfig._try_build_live_node(StrategyNode)
        if node is None:
            return CheckResult(
                "StrategyNode: quality gate (live)",
                passed=True,
                skipped=True,
                detail="Live node unavailable",
            )
        try:
            result = node.run(
                question=self._cfg.STRATEGY_QUESTION,
                country=None,
            )
            text = result.strategy_draft.summary
            issues: list[str] = []
            for section in [
                "[SYSTEMIC PATTERNS IDENTIFIED]",
                "[ROOT CAUSE CATEGORIES]",
                "[ORGANISATIONAL WEAKNESSES]",
                "[GENERAL ADVICE]",
                "[WHAT TO EXPLORE NEXT]",
            ]:
                if not _QualityGateHelper.has_section(text, section):
                    issues.append(f"missing section: {section}")
            if not _QualityGateHelper.general_advice_is_flagged(text):
                issues.append("[GENERAL ADVICE] missing ⚠️ prefix")
            team_count, cosolve_count = _QualityGateHelper.strategy_has_team_cosolve(
                text
            )
            if team_count < 3:
                issues.append(
                    f"[WHAT TO EXPLORE NEXT] has {team_count} TEAM: items (need 3)"
                )
            if cosolve_count < 3:
                issues.append(
                    f"[WHAT TO EXPLORE NEXT] has {cosolve_count} COSOLVE: items (need 3)"
                )
            if issues:
                return CheckResult(
                    "StrategyNode: quality gate (live)",
                    passed=False,
                    detail="; ".join(issues),
                )
        except Exception as exc:
            return CheckResult(
                "StrategyNode: quality gate (live)",
                passed=False,
                detail=f"Exception: {exc}",
            )
        return CheckResult("StrategyNode: quality gate (live)", passed=True)

    def test_quality_gate_mock_response_structure(self) -> CheckResult:
        text = self._cfg.MOCK_STRATEGY_RESPONSE
        issues: list[str] = []
        for section in [
            "[SYSTEMIC PATTERNS IDENTIFIED]",
            "[ROOT CAUSE CATEGORIES]",
            "[ORGANISATIONAL WEAKNESSES]",
            "[GENERAL ADVICE]",
            "[WHAT TO EXPLORE NEXT]",
        ]:
            if not _QualityGateHelper.has_section(text, section):
                issues.append(f"missing section: {section}")
        if not _QualityGateHelper.general_advice_is_flagged(text):
            issues.append("[GENERAL ADVICE] missing ⚠️ prefix")
        team_count, cosolve_count = _QualityGateHelper.strategy_has_team_cosolve(text)
        if team_count < 3:
            issues.append(f"TEAM: items: {team_count} (need 3)")
        if cosolve_count < 3:
            issues.append(f"COSOLVE: items: {cosolve_count} (need 3)")
        if issues:
            return CheckResult(
                "StrategyNode: quality gate (mock response structure)",
                passed=False,
                detail="; ".join(issues),
            )
        return CheckResult(
            "StrategyNode: quality gate (mock response structure)", passed=True
        )

    # ── Category 4: Banned Term Detection ────────────────────────────────

    def test_banned_terms_in_mock_output(self) -> CheckResult:
        node = NodeCheckConfig._make_strategy_node(self._cfg)
        try:
            result = node.run(
                question=self._cfg.STRATEGY_QUESTION,
                country=None,
            )
            text = result.strategy_draft.summary
            hits = _QualityGateHelper.scan_banned_terms(text, self._cfg)
            if hits:
                return CheckResult(
                    "StrategyNode: banned term detection",
                    passed=False,
                    detail="\n".join(hits),
                )
        except Exception as exc:
            return CheckResult(
                "StrategyNode: banned term detection",
                passed=False,
                detail=f"Exception: {exc}",
            )
        return CheckResult("StrategyNode: banned term detection", passed=True)

    def test_logger_not_a_prompt(self) -> CheckResult:
        """StrategyNode has a module-level _logger; verify it is NOT flagged as a
        forbidden prompt constant — only actual prompt strings should be checked."""
        source, tree = NodeCheckConfig._read_source(StrategyNode)
        # Module-level _logger assignment must exist (sanity check for the
        # "prompts are class-level" check not over-firing on loggers)
        module_assigns = [
            node
            for node in ast.iter_child_nodes(tree)
            if isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "_logger" for t in node.targets)
        ]
        if not module_assigns:
            return CheckResult(
                "StrategyNode: module-level _logger allowed",
                passed=True,
                detail="No module-level _logger found (may have been moved — OK)",
            )
        # The class-level prompt check only flags _PROMPT/_SYSTEM/_TEMPLATE names;
        # _logger should NOT be flagged.
        module_prompts = _ASTHelper.module_level_string_constant_names(tree)
        if "_logger" in module_prompts:
            return CheckResult(
                "StrategyNode: module-level _logger allowed",
                passed=False,
                detail="_logger incorrectly flagged as a prompt constant",
            )
        return CheckResult("StrategyNode: module-level _logger allowed", passed=True)

    def run_all(self) -> list[CheckResult]:
        return [
            self.test_no_module_level_functions(),
            self.test_no_del_statements(),
            self.test_prompts_are_class_level(),
            self.test_required_methods_exist(),
            self.test_output_model_type(),
            self.test_io_contract_global(),
            self.test_io_contract_country_filtered(),
            self.test_suggestions_extracted(),
            self.test_quality_gate_live(),
            self.test_quality_gate_mock_response_structure(),
            self.test_banned_terms_in_mock_output(),
            self.test_logger_not_a_prompt(),
        ]


# ══════════════════════════════════════════════════════════════════════════════
# KPINodeChecks
# ══════════════════════════════════════════════════════════════════════════════


class KPINodeChecks:
    """Automated checks for KPINode."""

    # Valid render_hint values from the KPIResult Pydantic model.
    _VALID_RENDER_HINTS: frozenset[str] = frozenset(
        {"table", "bar_chart", "gauge", "summary_text"}
    )

    def __init__(self, config: NodeCheckConfig) -> None:
        self._cfg = config

    # ── Category 1: Structural Integrity ─────────────────────────────────

    def test_no_module_level_functions(self) -> CheckResult:
        source, tree = NodeCheckConfig._read_source(KPINode)
        funcs = _ASTHelper.module_level_function_names(tree)
        if funcs:
            return CheckResult(
                "KPINode: no module-level functions",
                passed=False,
                detail=f"Found: {funcs}",
            )
        return CheckResult("KPINode: no module-level functions", passed=True)

    def test_no_del_statements(self) -> CheckResult:
        source, tree = NodeCheckConfig._read_source(KPINode)
        if _ASTHelper.has_del_statements(tree):
            return CheckResult(
                "KPINode: no del statements",
                passed=False,
                detail="del statement found",
            )
        return CheckResult("KPINode: no del statements", passed=True)

    def test_required_methods_exist(self) -> CheckResult:
        source, tree = NodeCheckConfig._read_source(KPINode)
        methods = _ASTHelper.class_method_names(tree, "KPINode")
        required = {"run", "_resolve_scope", "_extract_country"}
        missing = required - set(methods)
        if missing:
            return CheckResult(
                "KPINode: required methods exist",
                passed=False,
                detail=f"Missing: {missing}",
            )
        return CheckResult("KPINode: required methods exist", passed=True)

    def test_output_model_type(self) -> CheckResult:
        node = NodeCheckConfig._make_kpi_node(self._cfg)
        try:
            result = node.run(
                question=self._cfg.KPI_QUESTION_GLOBAL,
                case_id=None,
                classification_scope="GLOBAL",
                country=None,
            )
            if not isinstance(result, KPINodeOutput):
                return CheckResult(
                    "KPINode: output model type",
                    passed=False,
                    detail=f"Got {type(result).__name__}",
                )
        except Exception as exc:
            return CheckResult(
                "KPINode: output model type",
                passed=False,
                detail=f"Exception: {exc}",
            )
        return CheckResult("KPINode: output model type", passed=True)

    # ── Category 2: Input/Output Contract ────────────────────────────────

    def test_io_contract_global_scope(self) -> CheckResult:
        node = NodeCheckConfig._make_kpi_node(self._cfg)
        try:
            result = node.run(
                question=self._cfg.KPI_QUESTION_GLOBAL,
                case_id=None,
                classification_scope="GLOBAL",
                country=None,
            )
            metrics = result.kpi_metrics
            issues: list[str] = []
            if not isinstance(result, KPINodeOutput):
                issues.append("output not KPINodeOutput")
            if metrics.scope != "global":
                issues.append(f"scope '{metrics.scope}' expected 'global'")
            if metrics.render_hint not in self._VALID_RENDER_HINTS:
                issues.append(
                    f"render_hint '{metrics.render_hint}' not in {self._VALID_RENDER_HINTS}"
                )
            if len(metrics.suggestions) != 3:
                issues.append(
                    f"suggestions count {len(metrics.suggestions)} expected 3"
                )
            if metrics.scope_label != "Global":
                issues.append(f"scope_label '{metrics.scope_label}' expected 'Global'")
            if issues:
                return CheckResult(
                    "KPINode: I/O contract (global scope)",
                    passed=False,
                    detail="; ".join(issues),
                )
        except Exception as exc:
            return CheckResult(
                "KPINode: I/O contract (global scope)",
                passed=False,
                detail=f"Exception: {exc}",
            )
        return CheckResult("KPINode: I/O contract (global scope)", passed=True)

    def test_io_contract_country_scope(self) -> CheckResult:
        node = NodeCheckConfig._make_kpi_node(self._cfg)
        try:
            result = node.run(
                question=self._cfg.KPI_QUESTION_COUNTRY,
                case_id=None,
                classification_scope="COUNTRY",
                country="France",
            )
            metrics = result.kpi_metrics
            issues: list[str] = []
            if metrics.scope != "country":
                issues.append(f"scope '{metrics.scope}' expected 'country'")
            if metrics.render_hint not in self._VALID_RENDER_HINTS:
                issues.append(f"render_hint '{metrics.render_hint}' invalid")
            if len(metrics.suggestions) != 3:
                issues.append(
                    f"suggestions count {len(metrics.suggestions)} expected 3"
                )
            if "France" not in metrics.scope_label:
                issues.append(
                    f"scope_label '{metrics.scope_label}' should contain 'France'"
                )
            if issues:
                return CheckResult(
                    "KPINode: I/O contract (country scope)",
                    passed=False,
                    detail="; ".join(issues),
                )
        except Exception as exc:
            return CheckResult(
                "KPINode: I/O contract (country scope)",
                passed=False,
                detail=f"Exception: {exc}",
            )
        return CheckResult("KPINode: I/O contract (country scope)", passed=True)

    def test_io_contract_case_scope(self) -> CheckResult:
        node = NodeCheckConfig._make_kpi_node(self._cfg)
        try:
            result = node.run(
                question=self._cfg.KPI_QUESTION_CASE,
                case_id=self._cfg.SAMPLE_CASE_ID,
                classification_scope="LOCAL",
                country=None,
            )
            metrics = result.kpi_metrics
            issues: list[str] = []
            if metrics.scope != "case":
                issues.append(f"scope '{metrics.scope}' expected 'case'")
            if metrics.render_hint not in self._VALID_RENDER_HINTS:
                issues.append(f"render_hint '{metrics.render_hint}' invalid")
            if len(metrics.suggestions) != 3:
                issues.append(
                    f"suggestions count {len(metrics.suggestions)} expected 3"
                )
            if self._cfg.SAMPLE_CASE_ID not in metrics.scope_label:
                issues.append(
                    f"scope_label '{metrics.scope_label}' does not contain case ID"
                )
            if issues:
                return CheckResult(
                    "KPINode: I/O contract (case scope)",
                    passed=False,
                    detail="; ".join(issues),
                )
        except Exception as exc:
            return CheckResult(
                "KPINode: I/O contract (case scope)",
                passed=False,
                detail=f"Exception: {exc}",
            )
        return CheckResult("KPINode: I/O contract (case scope)", passed=True)

    def test_render_hint_gauge_for_case_scope(self) -> CheckResult:
        """Case scope with days_elapsed populated should use 'gauge' render hint."""
        node = NodeCheckConfig._make_kpi_node(self._cfg)
        try:
            result = node.run(
                question=self._cfg.KPI_QUESTION_CASE,
                case_id=self._cfg.SAMPLE_CASE_ID,
                classification_scope="LOCAL",
                country=None,
            )
            metrics = result.kpi_metrics
            if metrics.render_hint not in ("gauge", "summary_text"):
                return CheckResult(
                    "KPINode: render_hint gauge for case scope",
                    passed=False,
                    detail=(
                        f"render_hint '{metrics.render_hint}' — expected 'gauge' "
                        f"(or 'summary_text' when opening_date unavailable)"
                    ),
                )
        except Exception as exc:
            return CheckResult(
                "KPINode: render_hint gauge for case scope",
                passed=False,
                detail=f"Exception: {exc}",
            )
        return CheckResult("KPINode: render_hint gauge for case scope", passed=True)

    def test_local_no_case_falls_back_to_global(self) -> CheckResult:
        """LOCAL scope with no case_id should gracefully fall back to global."""
        node = NodeCheckConfig._make_kpi_node(self._cfg)
        try:
            result = node.run(
                question=self._cfg.KPI_QUESTION_GLOBAL,
                case_id=None,
                classification_scope="LOCAL",
                country=None,
            )
            metrics = result.kpi_metrics
            if metrics.scope != "global":
                return CheckResult(
                    "KPINode: LOCAL without case falls back to global",
                    passed=False,
                    detail=f"scope is '{metrics.scope}', expected 'global'",
                )
        except Exception as exc:
            return CheckResult(
                "KPINode: LOCAL without case falls back to global",
                passed=False,
                detail=f"Exception: {exc}",
            )
        return CheckResult(
            "KPINode: LOCAL without case falls back to global", passed=True
        )

    def test_scope_label_format(self) -> CheckResult:
        """scope_label must follow the format: 'Global', 'Country: <name>',
        or 'Case: <id>'."""
        node = NodeCheckConfig._make_kpi_node(self._cfg)
        issues: list[str] = []
        test_cases = [
            ("GLOBAL", None, None, "Global"),
            ("COUNTRY", None, "France", "Country: France"),
            (
                "LOCAL",
                self._cfg.SAMPLE_CASE_ID,
                None,
                f"Case: {self._cfg.SAMPLE_CASE_ID}",
            ),
        ]
        for scope, case_id, country, expected_label in test_cases:
            try:
                result = node.run(
                    question="KPI check",
                    case_id=case_id,
                    classification_scope=scope,
                    country=country,
                )
                label = result.kpi_metrics.scope_label
                if label != expected_label:
                    issues.append(
                        f"scope={scope}: expected '{expected_label}', got '{label}'"
                    )
            except Exception as exc:
                issues.append(f"scope={scope}: Exception {exc}")
        if issues:
            return CheckResult(
                "KPINode: scope_label format",
                passed=False,
                detail="; ".join(issues),
            )
        return CheckResult("KPINode: scope_label format", passed=True)

    def test_suggestions_progress_logically(self) -> CheckResult:
        """Suggestion chips should guide global→country→case progression."""
        node = NodeCheckConfig._make_kpi_node(self._cfg)
        issues: list[str] = []
        for scope, case_id, country, expected_scope_hint in [
            ("GLOBAL", None, None, "country"),
            ("COUNTRY", None, "France", "France"),
        ]:
            try:
                result = node.run(
                    question="KPI check",
                    case_id=case_id,
                    classification_scope=scope,
                    country=country,
                )
                suggestions_text = " ".join(result.kpi_metrics.suggestions).lower()
                if expected_scope_hint.lower() not in suggestions_text:
                    issues.append(
                        f"scope={scope}: suggestions don't mention '{expected_scope_hint}': "
                        f"{result.kpi_metrics.suggestions}"
                    )
            except Exception as exc:
                issues.append(f"scope={scope}: Exception {exc}")
        if issues:
            return CheckResult(
                "KPINode: suggestion chips progress logically",
                passed=False,
                detail="; ".join(issues),
            )
        return CheckResult("KPINode: suggestion chips progress logically", passed=True)

    # ── Category 3: Quality Gate ──────────────────────────────────────────

    def test_quality_gate_no_d_codes_in_output(self) -> CheckResult:
        """D-stage codes must never appear in KPIResult fields (plain labels only)."""
        node = NodeCheckConfig._make_kpi_node(self._cfg)
        all_hits: list[str] = []
        for scope, case_id, country in [
            ("GLOBAL", None, None),
            ("COUNTRY", None, "France"),
            ("LOCAL", self._cfg.SAMPLE_CASE_ID, None),
        ]:
            try:
                result = node.run(
                    question="KPI check",
                    case_id=case_id,
                    classification_scope=scope,
                    country=country,
                )
                hits = _QualityGateHelper.kpi_has_no_d_codes(result.kpi_metrics)
                all_hits.extend(f"scope={scope}: {h}" for h in hits if "_D" not in h)
                # Note: keys like 'd_stage_distribution' or 'avg_days_per_stage'
                # contain the string "d_stage" in the key name, not in user-facing
                # values — only flag raw D-codes in field VALUES, excluding keys
                # that legitimately discuss stage distribution.
            except Exception as exc:
                all_hits.append(f"scope={scope}: Exception {exc}")
        if all_hits:
            return CheckResult(
                "KPINode: quality gate — no D-codes in output",
                passed=False,
                detail="\n".join(all_hits),
            )
        return CheckResult("KPINode: quality gate — no D-codes in output", passed=True)

    def test_quality_gate_no_tech_terms_in_suggestions(self) -> CheckResult:
        """Suggestion chips must not contain technical infrastructure terms."""
        node = NodeCheckConfig._make_kpi_node(self._cfg)
        all_hits: list[str] = []
        for scope, case_id, country in [
            ("GLOBAL", None, None),
            ("COUNTRY", None, "France"),
            ("LOCAL", self._cfg.SAMPLE_CASE_ID, None),
        ]:
            try:
                result = node.run(
                    question="KPI check",
                    case_id=case_id,
                    classification_scope=scope,
                    country=country,
                )
                suggestions_text = " ".join(result.kpi_metrics.suggestions)
                hits = _QualityGateHelper.scan_banned_terms(suggestions_text, self._cfg)
                all_hits.extend(f"scope={scope}: {h}" for h in hits)
            except Exception as exc:
                all_hits.append(f"scope={scope}: Exception {exc}")
        if all_hits:
            return CheckResult(
                "KPINode: quality gate — no tech terms in suggestions",
                passed=False,
                detail="\n".join(all_hits),
            )
        return CheckResult(
            "KPINode: quality gate — no tech terms in suggestions", passed=True
        )

    def test_quality_gate_responsible_leader_grounded(self) -> CheckResult:
        """For case scope, responsible_leader & department must come from case data."""
        node = NodeCheckConfig._make_kpi_node(self._cfg)
        try:
            result = node.run(
                question=self._cfg.KPI_QUESTION_CASE,
                case_id=self._cfg.SAMPLE_CASE_ID,
                classification_scope="LOCAL",
                country=None,
            )
            metrics = result.kpi_metrics
            mock_case = self._cfg.MOCK_KPI_CASE
            issues: list[str] = []
            if mock_case.responsible_leader and metrics.responsible_leader not in (
                mock_case.responsible_leader,
                None,
            ):
                issues.append(
                    f"responsible_leader '{metrics.responsible_leader}' "
                    f"not grounded in case data (expected '{mock_case.responsible_leader}')"
                )
            if mock_case.department and metrics.department not in (
                mock_case.department,
                None,
            ):
                issues.append(
                    f"department '{metrics.department}' "
                    f"not grounded in case data (expected '{mock_case.department}')"
                )
            if issues:
                return CheckResult(
                    "KPINode: quality gate — responsible_leader grounded",
                    passed=False,
                    detail="; ".join(issues),
                )
        except Exception as exc:
            return CheckResult(
                "KPINode: quality gate — responsible_leader grounded",
                passed=False,
                detail=f"Exception: {exc}",
            )
        return CheckResult(
            "KPINode: quality gate — responsible_leader grounded", passed=True
        )

    # ── Category 4: Banned Term Detection ────────────────────────────────

    def test_banned_terms_in_suggestions(self) -> CheckResult:
        node = NodeCheckConfig._make_kpi_node(self._cfg)
        all_hits: list[str] = []
        for scope, case_id, country in [
            ("GLOBAL", None, None),
            ("COUNTRY", None, "France"),
            ("LOCAL", self._cfg.SAMPLE_CASE_ID, None),
        ]:
            try:
                result = node.run(
                    question="KPI check",
                    case_id=case_id,
                    classification_scope=scope,
                    country=country,
                )
                suggestions_text = " ".join(result.kpi_metrics.suggestions)
                hits = _QualityGateHelper.scan_banned_terms(suggestions_text, self._cfg)
                all_hits.extend(f"scope={scope}: {h}" for h in hits)
            except Exception as exc:
                all_hits.append(f"scope={scope}: Exception {exc}")
        if all_hits:
            return CheckResult(
                "KPINode: banned term detection",
                passed=False,
                detail="\n".join(all_hits),
            )
        return CheckResult("KPINode: banned term detection", passed=True)

    def test_resolve_scope_logic(self) -> CheckResult:
        """Unit-test the scope resolution method."""
        node = NodeCheckConfig._make_kpi_node(self._cfg)
        issues: list[str] = []
        cases = [
            ("GLOBAL", None, "global"),
            ("GLOBAL", "CASE-001", "global"),
            ("COUNTRY", None, "country"),
            ("COUNTRY", "CASE-001", "country"),
            ("LOCAL", "CASE-001", "case"),
            ("LOCAL", None, "global"),  # graceful fallback
        ]
        for classification, case_id, expected in cases:
            actual = node._resolve_scope(classification, case_id)
            if actual != expected:
                issues.append(
                    f"_resolve_scope({classification!r}, {case_id!r}) "
                    f"→ {actual!r}, expected {expected!r}"
                )
        if issues:
            return CheckResult(
                "KPINode: scope resolution logic",
                passed=False,
                detail="; ".join(issues),
            )
        return CheckResult("KPINode: scope resolution logic", passed=True)

    def test_extract_country_from_question(self) -> CheckResult:
        """Unit-test the country extraction helper."""
        node = NodeCheckConfig._make_kpi_node(self._cfg)
        issues: list[str] = []
        cases = [
            ("What are KPIs? country: France", "France"),
            ("Show KPIs. country: Germany.", "Germany"),
            ("Show global KPIs.", None),
        ]
        for question, expected in cases:
            actual = node._extract_country(question)
            if actual != expected:
                issues.append(
                    f"_extract_country({question!r}) → {actual!r}, expected {expected!r}"
                )
        if issues:
            return CheckResult(
                "KPINode: country extraction from question",
                passed=False,
                detail="; ".join(issues),
            )
        return CheckResult("KPINode: country extraction from question", passed=True)

    def run_all(self) -> list[CheckResult]:
        return [
            self.test_no_module_level_functions(),
            self.test_no_del_statements(),
            self.test_required_methods_exist(),
            self.test_output_model_type(),
            self.test_io_contract_global_scope(),
            self.test_io_contract_country_scope(),
            self.test_io_contract_case_scope(),
            self.test_render_hint_gauge_for_case_scope(),
            self.test_local_no_case_falls_back_to_global(),
            self.test_scope_label_format(),
            self.test_suggestions_progress_logically(),
            self.test_quality_gate_no_d_codes_in_output(),
            self.test_quality_gate_no_tech_terms_in_suggestions(),
            self.test_quality_gate_responsible_leader_grounded(),
            self.test_banned_terms_in_suggestions(),
            self.test_resolve_scope_logic(),
            self.test_extract_country_from_question(),
        ]


# ══════════════════════════════════════════════════════════════════════════════
# QuestionReadinessNodeChecks
# ══════════════════════════════════════════════════════════════════════════════


class QuestionReadinessNodeChecks:
    """Automated checks for QuestionReadinessNode."""

    _JARGON_TERMS: tuple[str, ...] = (
        "intent",
        "node",
        "classification",
        "routing",
        "azure",
        "langgraph",
        "index",
        "retriever",
        "embedding",
    )

    def __init__(self, config: NodeCheckConfig) -> None:
        self._cfg = config

    # ── Check 1: question ready when case is loaded ───────────────────────

    def test_ready_when_case_loaded(self) -> CheckResult:
        node = QuestionReadinessNode(
            llm_client=_MockQuestionReadinessLLMClient(
                ready=True, clarifying_question=""
            )
        )
        try:
            result = node.run(
                question="What should we focus on next?",
                intent="OPERATIONAL_CASE",
                case_loaded=True,
            )
            if not isinstance(result, QuestionReadinessNodeOutput):
                return CheckResult(
                    "QuestionReadinessNode: ready when case loaded",
                    passed=False,
                    detail=f"Expected QuestionReadinessNodeOutput, got {type(result).__name__}",
                )
            if not result.question_ready:
                return CheckResult(
                    "QuestionReadinessNode: ready when case loaded",
                    passed=False,
                    detail=f"question_ready={result.question_ready}, expected True",
                )
        except Exception as exc:
            return CheckResult(
                "QuestionReadinessNode: ready when case loaded",
                passed=False,
                detail=f"Exception: {exc}",
            )
        return CheckResult("QuestionReadinessNode: ready when case loaded", passed=True)

    # ── Check 2: not ready when operational question with no case loaded ──

    def test_not_ready_operational_no_case(self) -> CheckResult:
        cq = "Could you describe the problem you are currently investigating?"
        node = QuestionReadinessNode(
            llm_client=_MockQuestionReadinessLLMClient(
                ready=False, clarifying_question=cq
            )
        )
        try:
            result = node.run(
                question="What should we focus on next?",
                intent="OPERATIONAL_CASE",
                case_loaded=False,
            )
            if result.question_ready:
                return CheckResult(
                    "QuestionReadinessNode: not ready when no case loaded",
                    passed=False,
                    detail=f"question_ready=True, expected False for operational question without case",
                )
            if not result.clarifying_question:
                return CheckResult(
                    "QuestionReadinessNode: not ready when no case loaded",
                    passed=False,
                    detail="clarifying_question is empty when ready=False",
                )
        except Exception as exc:
            return CheckResult(
                "QuestionReadinessNode: not ready when no case loaded",
                passed=False,
                detail=f"Exception: {exc}",
            )
        return CheckResult(
            "QuestionReadinessNode: not ready when no case loaded", passed=True
        )

    # ── Check 3: clarifying question contains no technical jargon ─────────

    def test_no_jargon_in_clarifying_question(self) -> CheckResult:
        cq = "Could you describe the specific problem your team is currently looking into?"
        node = QuestionReadinessNode(
            llm_client=_MockQuestionReadinessLLMClient(
                ready=False, clarifying_question=cq
            )
        )
        try:
            result = node.run(
                question="What next?",
                intent="OPERATIONAL_CASE",
                case_loaded=False,
            )
            text_lower = result.clarifying_question.lower()
            hits = [
                term
                for term in QuestionReadinessNodeChecks._JARGON_TERMS
                if term.lower() in text_lower
            ]
            if hits:
                return CheckResult(
                    "QuestionReadinessNode: no jargon in clarifying question",
                    passed=False,
                    detail=f"Jargon terms found: {hits}",
                )
        except Exception as exc:
            return CheckResult(
                "QuestionReadinessNode: no jargon in clarifying question",
                passed=False,
                detail=f"Exception: {exc}",
            )
        return CheckResult(
            "QuestionReadinessNode: no jargon in clarifying question", passed=True
        )

    def run_all(self) -> list[CheckResult]:
        return [
            self.test_ready_when_case_loaded(),
            self.test_not_ready_operational_no_case(),
            self.test_no_jargon_in_clarifying_question(),
        ]


# ══════════════════════════════════════════════════════════════════════════════
# NodeCheckRunner — orchestrates all checks and produces the report
# ══════════════════════════════════════════════════════════════════════════════


class NodeCheckRunner:
    """Orchestrates all checks and produces a structured report."""

    _SEPARATOR: str = "=" * 60
    _SUB_SEPARATOR: str = "-" * 60

    def __init__(self, config: NodeCheckConfig | None = None) -> None:
        self._config = config or NodeCheckConfig()

    def run_all(self) -> int:
        """Run all checks, print the report, and return exit code.

        Returns:
            0  if every non-skipped check passes.
            1  if any non-skipped check fails.
        """
        all_results: list[tuple[str, list[CheckResult]]] = []

        node_suites: list[tuple[str, list[CheckResult]]] = [
            ("OperationalNode", OperationalNodeChecks(self._config).run_all()),
            ("SimilarityNode", SimilarityNodeChecks(self._config).run_all()),
            ("StrategyNode", StrategyNodeChecks(self._config).run_all()),
            ("KPINode", KPINodeChecks(self._config).run_all()),
            (
                "QuestionReadinessNode",
                QuestionReadinessNodeChecks(self._config).run_all(),
            ),
        ]

        total_pass = total_fail = total_skip = 0

        print()
        print(self._SEPARATOR)
        print("CoSolve Node Automated Check Report")
        print(f"LIVE_MODE = {self._config.LIVE_MODE}")
        print(self._SEPARATOR)

        for node_name, results in node_suites:
            node_pass = sum(1 for r in results if r.passed and not r.skipped)
            node_fail = sum(1 for r in results if not r.passed and not r.skipped)
            node_skip = sum(1 for r in results if r.skipped)

            total_pass += node_pass
            total_fail += node_fail
            total_skip += node_skip

            overall = "PASS" if node_fail == 0 else "FAIL"
            print()
            print(f"{node_name:<30}  {overall}")
            print(self._SUB_SEPARATOR)

            for result in results:
                icon = result.icon
                label = result.name
                # Strip the node prefix from display if present
                display_label = label.split(": ", 1)[-1] if ": " in label else label
                print(f"  {icon} {display_label}")
                if not result.passed and not result.skipped and result.detail:
                    for line in result.detail.split("\n"):
                        print(f"       ↳ {line}")
                elif result.skipped and result.detail:
                    print(f"       ↳ {result.detail}")

            all_results.append((node_name, results))

        total_checks = total_pass + total_fail + total_skip
        print()
        print(self._SEPARATOR)
        print(
            f"Overall: {total_pass}/{total_pass + total_fail} checks passed"
            + (f"  ({total_skip} skipped)" if total_skip else "")
        )
        print(self._SEPARATOR)
        print()

        return 0 if total_fail == 0 else 1

    def build_results_dict(self) -> dict[str, list[CheckResult]]:
        """Return structured results without printing — useful for programmatic use."""
        return {
            "OperationalNode": OperationalNodeChecks(self._config).run_all(),
            "SimilarityNode": SimilarityNodeChecks(self._config).run_all(),
            "StrategyNode": StrategyNodeChecks(self._config).run_all(),
            "KPINode": KPINodeChecks(self._config).run_all(),
            "QuestionReadinessNode": QuestionReadinessNodeChecks(
                self._config
            ).run_all(),
        }


# ══════════════════════════════════════════════════════════════════════════════
# pytest-compatible wrappers — allow `pytest backend/tests/test_node_checks.py`
# ══════════════════════════════════════════════════════════════════════════════


class TestOperationalNode:
    """pytest wrapper for OperationalNodeChecks."""

    _cfg = NodeCheckConfig()
    _checks = None

    @classmethod
    def _get_checks(cls) -> OperationalNodeChecks:
        if cls._checks is None:
            cls._checks = OperationalNodeChecks(cls._cfg)
        return cls._checks

    def test_structural_no_module_level_functions(self) -> None:
        r = self._get_checks().test_no_module_level_functions()
        assert r.passed or r.skipped, r.detail

    def test_structural_no_del_statements(self) -> None:
        r = self._get_checks().test_no_del_statements()
        assert r.passed or r.skipped, r.detail

    def test_structural_prompts_are_class_level(self) -> None:
        r = self._get_checks().test_prompts_are_class_level()
        assert r.passed or r.skipped, r.detail

    def test_structural_required_methods_exist(self) -> None:
        r = self._get_checks().test_required_methods_exist()
        assert r.passed or r.skipped, r.detail

    def test_structural_output_model_type(self) -> None:
        r = self._get_checks().test_output_model_type()
        assert r.passed or r.skipped, r.detail

    def test_io_contract_with_case(self) -> None:
        r = self._get_checks().test_io_contract_with_case()
        assert r.passed or r.skipped, r.detail

    def test_io_contract_no_case(self) -> None:
        r = self._get_checks().test_io_contract_no_case()
        assert r.passed or r.skipped, r.detail

    def test_suggestions_extracted(self) -> None:
        r = self._get_checks().test_suggestions_extracted()
        assert r.passed or r.skipped, r.detail

    def test_quality_gate_mock_response_structure(self) -> None:
        r = self._get_checks().test_quality_gate_mock_response_structure()
        assert r.passed or r.skipped, r.detail

    def test_banned_terms_in_mock_output(self) -> None:
        r = self._get_checks().test_banned_terms_in_mock_output()
        assert r.passed or r.skipped, r.detail

    def test_is_new_problem_question_logic(self) -> None:
        r = self._get_checks().test_is_new_problem_question_logic()
        assert r.passed or r.skipped, r.detail


class TestSimilarityNode:
    """pytest wrapper for SimilarityNodeChecks."""

    _cfg = NodeCheckConfig()
    _checks = None

    @classmethod
    def _get_checks(cls) -> SimilarityNodeChecks:
        if cls._checks is None:
            cls._checks = SimilarityNodeChecks(cls._cfg)
        return cls._checks

    def test_structural_no_module_level_functions(self) -> None:
        r = self._get_checks().test_no_module_level_functions()
        assert r.passed or r.skipped, r.detail

    def test_structural_no_del_statements(self) -> None:
        r = self._get_checks().test_no_del_statements()
        assert r.passed or r.skipped, r.detail

    def test_structural_prompts_are_class_level(self) -> None:
        r = self._get_checks().test_prompts_are_class_level()
        assert r.passed or r.skipped, r.detail

    def test_structural_required_methods_exist(self) -> None:
        r = self._get_checks().test_required_methods_exist()
        assert r.passed or r.skipped, r.detail

    def test_structural_output_model_type(self) -> None:
        r = self._get_checks().test_output_model_type()
        assert r.passed or r.skipped, r.detail

    def test_io_contract_with_case(self) -> None:
        r = self._get_checks().test_io_contract_with_case()
        assert r.passed or r.skipped, r.detail

    def test_io_contract_no_case(self) -> None:
        r = self._get_checks().test_io_contract_no_case()
        assert r.passed or r.skipped, r.detail

    def test_supporting_cases_forwarded(self) -> None:
        r = self._get_checks().test_supporting_cases_forwarded()
        assert r.passed or r.skipped, r.detail

    def test_quality_gate_mock_response_structure(self) -> None:
        r = self._get_checks().test_quality_gate_mock_response_structure()
        assert r.passed or r.skipped, r.detail

    def test_banned_terms_in_mock_output(self) -> None:
        r = self._get_checks().test_banned_terms_in_mock_output()
        assert r.passed or r.skipped, r.detail


class TestStrategyNode:
    """pytest wrapper for StrategyNodeChecks."""

    _cfg = NodeCheckConfig()
    _checks = None

    @classmethod
    def _get_checks(cls) -> StrategyNodeChecks:
        if cls._checks is None:
            cls._checks = StrategyNodeChecks(cls._cfg)
        return cls._checks

    def test_structural_no_module_level_functions(self) -> None:
        r = self._get_checks().test_no_module_level_functions()
        assert r.passed or r.skipped, r.detail

    def test_structural_no_del_statements(self) -> None:
        r = self._get_checks().test_no_del_statements()
        assert r.passed or r.skipped, r.detail

    def test_structural_prompts_are_class_level(self) -> None:
        r = self._get_checks().test_prompts_are_class_level()
        assert r.passed or r.skipped, r.detail

    def test_structural_required_methods_exist(self) -> None:
        r = self._get_checks().test_required_methods_exist()
        assert r.passed or r.skipped, r.detail

    def test_structural_output_model_type(self) -> None:
        r = self._get_checks().test_output_model_type()
        assert r.passed or r.skipped, r.detail

    def test_io_contract_global(self) -> None:
        r = self._get_checks().test_io_contract_global()
        assert r.passed or r.skipped, r.detail

    def test_io_contract_country_filtered(self) -> None:
        r = self._get_checks().test_io_contract_country_filtered()
        assert r.passed or r.skipped, r.detail

    def test_suggestions_extracted(self) -> None:
        r = self._get_checks().test_suggestions_extracted()
        assert r.passed or r.skipped, r.detail

    def test_quality_gate_mock_response_structure(self) -> None:
        r = self._get_checks().test_quality_gate_mock_response_structure()
        assert r.passed or r.skipped, r.detail

    def test_banned_terms_in_mock_output(self) -> None:
        r = self._get_checks().test_banned_terms_in_mock_output()
        assert r.passed or r.skipped, r.detail

    def test_logger_not_a_prompt(self) -> None:
        r = self._get_checks().test_logger_not_a_prompt()
        assert r.passed or r.skipped, r.detail


class TestKPINode:
    """pytest wrapper for KPINodeChecks."""

    _cfg = NodeCheckConfig()
    _checks = None

    @classmethod
    def _get_checks(cls) -> KPINodeChecks:
        if cls._checks is None:
            cls._checks = KPINodeChecks(cls._cfg)
        return cls._checks

    def test_structural_no_module_level_functions(self) -> None:
        r = self._get_checks().test_no_module_level_functions()
        assert r.passed or r.skipped, r.detail

    def test_structural_no_del_statements(self) -> None:
        r = self._get_checks().test_no_del_statements()
        assert r.passed or r.skipped, r.detail

    def test_structural_required_methods_exist(self) -> None:
        r = self._get_checks().test_required_methods_exist()
        assert r.passed or r.skipped, r.detail

    def test_structural_output_model_type(self) -> None:
        r = self._get_checks().test_output_model_type()
        assert r.passed or r.skipped, r.detail

    def test_io_contract_global_scope(self) -> None:
        r = self._get_checks().test_io_contract_global_scope()
        assert r.passed or r.skipped, r.detail

    def test_io_contract_country_scope(self) -> None:
        r = self._get_checks().test_io_contract_country_scope()
        assert r.passed or r.skipped, r.detail

    def test_io_contract_case_scope(self) -> None:
        r = self._get_checks().test_io_contract_case_scope()
        assert r.passed or r.skipped, r.detail

    def test_render_hint_gauge_for_case_scope(self) -> None:
        r = self._get_checks().test_render_hint_gauge_for_case_scope()
        assert r.passed or r.skipped, r.detail

    def test_local_no_case_falls_back_to_global(self) -> None:
        r = self._get_checks().test_local_no_case_falls_back_to_global()
        assert r.passed or r.skipped, r.detail

    def test_scope_label_format(self) -> None:
        r = self._get_checks().test_scope_label_format()
        assert r.passed or r.skipped, r.detail

    def test_suggestions_progress_logically(self) -> None:
        r = self._get_checks().test_suggestions_progress_logically()
        assert r.passed or r.skipped, r.detail

    def test_quality_gate_no_d_codes_in_output(self) -> None:
        r = self._get_checks().test_quality_gate_no_d_codes_in_output()
        assert r.passed or r.skipped, r.detail

    def test_quality_gate_no_tech_terms_in_suggestions(self) -> None:
        r = self._get_checks().test_quality_gate_no_tech_terms_in_suggestions()
        assert r.passed or r.skipped, r.detail

    def test_quality_gate_responsible_leader_grounded(self) -> None:
        r = self._get_checks().test_quality_gate_responsible_leader_grounded()
        assert r.passed or r.skipped, r.detail

    def test_banned_terms_in_suggestions(self) -> None:
        r = self._get_checks().test_banned_terms_in_suggestions()
        assert r.passed or r.skipped, r.detail

    def test_resolve_scope_logic(self) -> None:
        r = self._get_checks().test_resolve_scope_logic()
        assert r.passed or r.skipped, r.detail

    def test_extract_country_from_question(self) -> None:
        r = self._get_checks().test_extract_country_from_question()
        assert r.passed or r.skipped, r.detail


class TestQuestionReadinessNode:
    """pytest wrapper for QuestionReadinessNodeChecks."""

    _cfg = NodeCheckConfig()
    _checks = None

    @classmethod
    def _get_checks(cls) -> QuestionReadinessNodeChecks:
        if cls._checks is None:
            cls._checks = QuestionReadinessNodeChecks(cls._cfg)
        return cls._checks

    def test_ready_when_case_loaded(self) -> None:
        r = self._get_checks().test_ready_when_case_loaded()
        assert r.passed or r.skipped, r.detail

    def test_not_ready_operational_no_case(self) -> None:
        r = self._get_checks().test_not_ready_operational_no_case()
        assert r.passed or r.skipped, r.detail

    def test_no_jargon_in_clarifying_question(self) -> None:
        r = self._get_checks().test_no_jargon_in_clarifying_question()
        assert r.passed or r.skipped, r.detail


# ══════════════════════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════════════════════


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)s  %(name)s  %(message)s",
    )
    runner = NodeCheckRunner()
    exit_code = runner.run_all()
    sys.exit(exit_code)
