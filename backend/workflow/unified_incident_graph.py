from __future__ import annotations

import logging
from typing import Any, Callable, TypedDict, cast

from langgraph.graph import StateGraph
from opentelemetry import trace

_graph_logger = logging.getLogger("unified_incident_graph")
_tracer = trace.get_tracer("cosolve.langgraph")

from backend.ai.escalation_controller import EscalationController
from backend.workflow.models import (
    ContextNodeOutput,
    KPIInterpretation,
    KPIResult,
    FinalResponsePayload,
    IntentClassificationResult,
    OperationalPayload,
    QuestionReadinessNodeOutput,
    ReflectionResult,
    SimilarityPayload,
    SimilarityReflectionAssessment,
    StrategyPayload,
)
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


class IncidentGraphState(TypedDict, total=False):
    case_id: str | None
    question: str
    case_context: dict | None
    case_status: str | None
    current_d_state: str | None
    classification: IntentClassificationResult | None
    route: str | None
    operational_draft: OperationalPayload | None
    operational_result: OperationalPayload | None
    operational_reflection: ReflectionResult | None
    operational_escalated: bool
    similarity_draft: SimilarityPayload | None
    similarity_result: SimilarityPayload | None
    similarity_reflection: SimilarityReflectionAssessment | None
    similarity_escalated: bool
    strategy_draft: StrategyPayload | None
    strategy_result: StrategyPayload | None
    strategy_reflection: ReflectionResult | None
    strategy_escalated: bool
    strategy_fail_section: str | None
    strategy_fail_reason: str | None
    strategy_response: str | None
    kpi_metrics: KPIResult | None
    kpi_interpretation: KPIInterpretation | None
    final_response: dict | None
    question_ready: bool
    clarifying_question: str
    _last_node: str


class UnifiedIncidentGraph:
    def __init__(
        self,
        start_node: StartNode,
        context_node: ContextNode,
        intent_classification_node: IntentClassificationNode,
        question_readiness_node: QuestionReadinessNode,
        router_node: RouterNode,
        operational_node: OperationalNode,
        operational_reflection_node: OperationalReflectionNode,
        operational_escalation_node: OperationalEscalationNode,
        similarity_node: SimilarityNode,
        similarity_reflection_node: SimilarityReflectionNode,
        strategy_node: StrategyNode,
        strategy_reflection_node: StrategyReflectionNode,
        strategy_escalation_node: StrategyEscalationNode,
        kpi_node: KPINode,
        kpi_reflection_node: KPIReflectionNode,
        response_formatter_node: ResponseFormatterNode,
        end_node: EndNode,
        escalation_controller: EscalationController,
    ) -> None:
        self._start_node = start_node
        self._context_node = context_node
        self._intent_classification_node = intent_classification_node
        self._question_readiness_node = question_readiness_node
        self._router_node = router_node
        self._operational_node = operational_node
        self._operational_reflection_node = operational_reflection_node
        self._operational_escalation_node = operational_escalation_node
        self._similarity_node = similarity_node
        self._similarity_reflection_node = similarity_reflection_node
        self._strategy_node = strategy_node
        self._strategy_reflection_node = strategy_reflection_node
        self._strategy_escalation_node = strategy_escalation_node
        self._kpi_node = kpi_node
        self._kpi_reflection_node = kpi_reflection_node
        self._response_formatter_node = response_formatter_node
        self._end_node = end_node
        self._escalation_controller = escalation_controller

        graph = StateGraph(IncidentGraphState)
        graph.add_node("start_node", self._start)
        graph.add_node("context_node", self._context)
        graph.add_node("intent_classification_node", self._intent_classification)
        graph.add_node("question_readiness_node", self._question_readiness)
        graph.add_node("router_node", self._router)
        graph.add_node("operational_node", self._operational)
        graph.add_node("operational_reflection_node", self._operational_reflection)
        graph.add_node("operational_escalation_node", self._operational_escalation)
        graph.add_node("similarity_node", self._similarity)
        graph.add_node("similarity_reflection_node", self._similarity_reflection)
        graph.add_node("strategy_node", self._strategy)
        graph.add_node("strategy_reflection_node", self._strategy_reflection)
        graph.add_node("strategy_escalation_node", self._strategy_escalation)
        graph.add_node("kpi_node", self._kpi)
        graph.add_node("kpi_reflection_node", self._kpi_reflection)
        graph.add_node("response_formatter_node", self._response_formatter)
        graph.add_node("end_node", self._end)

        graph.set_entry_point("start_node")
        graph.set_finish_point("end_node")

        graph.add_edge("start_node", "context_node")
        graph.add_edge("context_node", "intent_classification_node")
        graph.add_edge("intent_classification_node", "question_readiness_node")
        # IntentReflectionNode removed: coerce_raw() in intent_coercion.py
        # guarantees schema validity before this point — LLM reflection
        # cannot catch failures that coercion has already prevented.
        # READY routes directly to router_node. Retired node retained in
        # intent_reflection_node.py for reference.
        graph.add_conditional_edges(
            "question_readiness_node",
            self._route_question_readiness,
            {
                "READY": "router_node",
                "NOT_READY": "response_formatter_node",
            },
        )

        graph.add_conditional_edges(
            "router_node",
            self._route_intent,
            {
                "OPERATIONAL_CASE": "operational_node",
                "SIMILARITY_SEARCH": "similarity_node",
                "STRATEGY_ANALYSIS": "strategy_node",
                "KPI_ANALYSIS": "kpi_node",
            },
        )

        graph.add_edge("operational_node", "operational_reflection_node")
        graph.add_conditional_edges(
            "operational_reflection_node",
            self._route_operational_escalation,
            {
                "ESCALATE": "operational_escalation_node",
                "CONTINUE": "response_formatter_node",
            },
        )
        graph.add_edge("operational_escalation_node", "operational_reflection_node")

        graph.add_edge("similarity_node", "similarity_reflection_node")
        graph.add_edge("similarity_reflection_node", "response_formatter_node")

        graph.add_edge("strategy_node", "strategy_reflection_node")
        graph.add_conditional_edges(
            "strategy_reflection_node",
            self._route_strategy_escalation,
            {
                "ESCALATE": "strategy_escalation_node",
                "CONTINUE": "response_formatter_node",
            },
        )
        graph.add_edge("strategy_escalation_node", "strategy_reflection_node")

        graph.add_edge("kpi_node", "kpi_reflection_node")
        graph.add_edge("kpi_reflection_node", "response_formatter_node")

        graph.add_edge("response_formatter_node", "end_node")
        self._graph = graph.compile()


    def invoke(self, initial_state: IncidentGraphState) -> IncidentGraphState:
        return self._graph.invoke(initial_state)

    def _traced_node(
        self,
        name: str,
        fn: Callable[..., Any],
        state: IncidentGraphState,
        **kwargs: Any,
    ) -> IncidentGraphState:
        import json as _json, datetime as _dt, pathlib as _pathlib
        with _tracer.start_as_current_span(f"node.{name}") as span:
            span.set_attribute("cosolve.case_id", state.get("case_id", "") or "")
            span.set_attribute("cosolve.route", state.get("route", "") or "")
            _prev = state.get("_last_node") or "entry"
            _t0 = _dt.datetime.utcnow()
            result = fn(state, **kwargs)
            _t1 = _dt.datetime.utcnow()
            _log_path = _pathlib.Path(__file__).parents[2] / "logs" / "node_transitions.jsonl"
            _log_path.parent.mkdir(exist_ok=True)
            try:
                with open(_log_path, "a") as _f:
                    _f.write(_json.dumps({
                        "timestamp": _t0.isoformat(),
                        "trace_id": state.get("trace_id", ""),
                        "from_node": _prev,
                        "to_node": name,
                        "route": state.get("route", "") or "",
                        "case_id": state.get("case_id", "") or "",
                        "duration_ms": round((_t1 - _t0).total_seconds() * 1000, 1)
                    }) + "\n")
            except OSError:
                pass
            if isinstance(result, dict):
                result["_last_node"] = name
            return result

    def _start(self, state: IncidentGraphState) -> IncidentGraphState:
        return self._traced_node("start", lambda s: cast(IncidentGraphState, self._start_node.run()), state)

    def _context(self, state: IncidentGraphState) -> IncidentGraphState:
        def _run(s: IncidentGraphState) -> IncidentGraphState:
            output: ContextNodeOutput = self._context_node.run(s.get("case_id"))
            return cast(IncidentGraphState, output.model_dump())
        return self._traced_node("context", _run, state)

    def _intent_classification(self, state: IncidentGraphState) -> IncidentGraphState:
        def _run(s: IncidentGraphState) -> IncidentGraphState:
            output = self._intent_classification_node.run(
                question=str(s.get("question") or ""),
                case_id=s.get("case_id"),
            )
            return cast(IncidentGraphState, output.model_dump())
        return self._traced_node("intent_classification", _run, state)

    def _question_readiness(self, state: IncidentGraphState) -> IncidentGraphState:
        def _run(s: IncidentGraphState) -> IncidentGraphState:
            classification = s.get("classification")
            intent = ""
            if isinstance(classification, dict):
                intent = str(classification.get("intent") or "")
            elif classification is not None:
                intent = str(classification.intent)
            case_loaded = bool(
                s.get("case_id") and str(s.get("case_id") or "").strip()
            )
            output: QuestionReadinessNodeOutput = self._question_readiness_node.run(
                question=str(s.get("question") or ""),
                intent=intent,
                case_loaded=case_loaded,
            )
            return cast(IncidentGraphState, output.model_dump())
        return self._traced_node("question_readiness", _run, state)

    def _route_question_readiness(self, state: IncidentGraphState) -> str:
        if not state.get("question_ready", True):
            _graph_logger.info(
                "[GRAPH_DEBUG] question not ready — short-circuiting to response_formatter"
            )
            return "NOT_READY"
        return "READY"

    def _router(self, state: IncidentGraphState) -> IncidentGraphState:
        def _run(s: IncidentGraphState) -> IncidentGraphState:
            classification = s.get("classification")
            if classification is None:
                raise ValueError("classification is required before routing")
            if isinstance(classification, dict):
                classification = IntentClassificationResult.model_validate(classification)
            output = self._router_node.run(classification)
            return cast(IncidentGraphState, output.model_dump())
        return self._traced_node("router", _run, state)

    def _operational(self, state: IncidentGraphState) -> IncidentGraphState:
        def _run(s: IncidentGraphState) -> IncidentGraphState:
            case_id = s.get("case_id")
            case_context = s.get("case_context")
            question = str(s.get("question") or "")

            is_new_problem = self._operational_reflection_node._is_new_problem_bypass(
                question, "", case_loaded=False
            )

            if (not case_id or not isinstance(case_context, dict)) and not is_new_problem:
                stub = OperationalPayload(
                    current_state="No case loaded",
                    current_state_recommendations=(
                        "No case is currently loaded. Please open or create a case "
                        "in the Case Board before asking operational questions."
                    ),
                    next_state_preview="",
                )
                return cast(IncidentGraphState, {"operational_draft": stub.model_dump()})

            case_status = self._extract_case_status(case_context)
            output = self._operational_node.run(
                question=question,
                case_id=case_id or "",
                case_context=case_context if isinstance(case_context, dict) else {},
                current_d_state=s.get("current_d_state"),
                case_status=case_status,
            )
            return cast(IncidentGraphState, output.model_dump())
        return self._traced_node("operational", _run, state)

    def _operational_reflection(self, state: IncidentGraphState) -> IncidentGraphState:
        def _run(s: IncidentGraphState) -> IncidentGraphState:
            draft = s.get("operational_draft")
            if draft is None:
                raise ValueError("operational_draft is required before reflection")
            if isinstance(draft, dict):
                draft = OperationalPayload.model_validate(draft)
            output = self._operational_reflection_node.run(
                question=str(s.get("question") or ""),
                draft=draft,
            )
            return cast(IncidentGraphState, output.model_dump())
        return self._traced_node("operational_reflection", _run, state)

    def _similarity(self, state: IncidentGraphState) -> IncidentGraphState:
        def _run(s: IncidentGraphState) -> IncidentGraphState:
            case_context = s.get("case_context")
            case_status_sim = (
                self._extract_case_status(case_context)
                if isinstance(case_context, dict)
                else None
            )
            output = self._similarity_node.run(
                question=str(s.get("question") or ""),
                case_id=s.get("case_id"),
                country=self._resolve_country(s),
                case_context=case_context,
                case_status=case_status_sim,
            )
            return cast(IncidentGraphState, output.model_dump())
        return self._traced_node("similarity", _run, state)

    def _similarity_reflection(self, state: IncidentGraphState) -> IncidentGraphState:
        def _run(s: IncidentGraphState) -> IncidentGraphState:
            draft = s.get("similarity_draft")
            if draft is None:
                raise ValueError("similarity_draft is required before reflection")
            if isinstance(draft, dict):
                draft = SimilarityPayload.model_validate(draft)
            output = self._similarity_reflection_node.run(
                question=str(s.get("question") or ""),
                draft=draft,
            )
            return cast(IncidentGraphState, output.model_dump())
        return self._traced_node("similarity_reflection", _run, state)

    def _strategy(self, state: IncidentGraphState) -> IncidentGraphState:
        def _run(s: IncidentGraphState) -> IncidentGraphState:
            output = self._strategy_node.run(
                question=str(s.get("question") or ""),
                country=self._resolve_country(s),
            )
            return cast(IncidentGraphState, output.model_dump())
        return self._traced_node("strategy", _run, state)

    def _strategy_reflection(self, state: IncidentGraphState) -> IncidentGraphState:
        def _run(s: IncidentGraphState) -> IncidentGraphState:
            draft = s.get("strategy_draft")
            if draft is None:
                raise ValueError("strategy_draft is required before reflection")
            if isinstance(draft, dict):
                draft = StrategyPayload.model_validate(draft)
            output = self._strategy_reflection_node.run(
                question=str(s.get("question") or ""),
                draft=draft,
            )
            return cast(IncidentGraphState, output.model_dump())
        return self._traced_node("strategy_reflection", _run, state)

    def _operational_escalation(self, state: IncidentGraphState) -> IncidentGraphState:
        def _run(s: IncidentGraphState) -> IncidentGraphState:
            case_id = s.get("case_id")
            case_context = s.get("case_context")
            if not case_id or not isinstance(case_context, dict):
                stub = OperationalPayload(
                    current_state="No case loaded",
                    current_state_recommendations=(
                        "No case is currently loaded. Please open or create a case "
                        "in the Case Board before asking operational questions."
                    ),
                    next_state_preview="",
                )
                return cast(
                    IncidentGraphState,
                    {"operational_draft": stub.model_dump(), "operational_escalated": True},
                )
            case_status = self._extract_case_status(case_context)
            output = self._operational_escalation_node.run(
                question=str(s.get("question") or ""),
                case_id=case_id,
                case_context=case_context,
                current_d_state=s.get("current_d_state"),
                state=dict(s),
                case_status=case_status,
            )
            result = cast(IncidentGraphState, output.model_dump())
            result["operational_escalated"] = True
            return result
        return self._traced_node("operational_escalation", _run, state)

    def _strategy_escalation(self, state: IncidentGraphState) -> IncidentGraphState:
        def _run(s: IncidentGraphState) -> IncidentGraphState:
            strategy_result = s.get("strategy_result")
            strategy_response = ""
            if isinstance(strategy_result, dict):
                strategy_response = str(strategy_result.get("summary") or "")
            elif hasattr(strategy_result, "summary"):
                strategy_response = str(strategy_result.summary)
            escalation_state = dict(s)
            escalation_state["strategy_response"] = strategy_response
            output = self._strategy_escalation_node.run(
                question=str(s.get("question") or ""),
                country=self._resolve_country(s),
                state=escalation_state,
            )
            result = cast(IncidentGraphState, output.model_dump())
            result["strategy_escalated"] = True
            return result
        return self._traced_node("strategy_escalation", _run, state)

    def _kpi(self, state: IncidentGraphState) -> IncidentGraphState:
        def _run(s: IncidentGraphState) -> IncidentGraphState:
            classification = s.get("classification")
            if isinstance(classification, dict):
                classification = IntentClassificationResult.model_validate(classification)
            classification_scope = (
                classification.scope if classification is not None else "GLOBAL"
            )
            output = self._kpi_node.run(
                question=str(s.get("question") or ""),
                case_id=s.get("case_id"),
                classification_scope=classification_scope,
                country=self._resolve_country(s),
            )
            return cast(IncidentGraphState, output.model_dump())
        return self._traced_node("kpi", _run, state)

    def _kpi_reflection(self, state: IncidentGraphState) -> IncidentGraphState:
        def _run(s: IncidentGraphState) -> IncidentGraphState:
            metrics = s.get("kpi_metrics")
            if metrics is None:
                raise ValueError("kpi_metrics is required before reflection")
            if isinstance(metrics, dict):
                metrics = KPIResult.model_validate(metrics)
            output = self._kpi_reflection_node.run(
                question=str(s.get("question") or ""),
                metrics=metrics,
            )
            return cast(IncidentGraphState, output.model_dump())
        return self._traced_node("kpi_reflection", _run, state)

    def _response_formatter(self, state: IncidentGraphState) -> IncidentGraphState:
        def _run(s: IncidentGraphState) -> IncidentGraphState:
            classification = s.get("classification")
            if isinstance(classification, dict):
                classification = IntentClassificationResult.model_validate(classification)
            operational_result = s.get("operational_result")
            if isinstance(operational_result, dict):
                operational_result = OperationalPayload.model_validate(operational_result)
            similarity_result = s.get("similarity_result")
            if isinstance(similarity_result, dict):
                similarity_result = SimilarityPayload.model_validate(similarity_result)
            strategy_result = s.get("strategy_result")
            if isinstance(strategy_result, dict):
                strategy_result = StrategyPayload.model_validate(strategy_result)
            kpi_interpretation = s.get("kpi_interpretation")
            if isinstance(kpi_interpretation, dict):
                kpi_interpretation = KPIInterpretation.model_validate(kpi_interpretation)
            output = self._response_formatter_node.run(
                classification=classification,
                operational_result=operational_result,
                similarity_result=similarity_result,
                strategy_result=strategy_result,
                kpi_interpretation=kpi_interpretation,
            )
            return cast(IncidentGraphState, output.model_dump())
        return self._traced_node("response_formatter", _run, state)

    def _end(self, state: IncidentGraphState) -> IncidentGraphState:
        def _run(s: IncidentGraphState) -> IncidentGraphState:
            response = s.get("final_response")
            if response is None:
                raise ValueError("final_response is required for end node")
            payload = FinalResponsePayload.model_validate(response)
            return {"final_response": self._end_node.run(payload).model_dump()}
        return self._traced_node("end", _run, state)

    def _route_intent(self, state: IncidentGraphState) -> str:
        route = state.get("route")
        _graph_logger.info("[GRAPH_DEBUG] routing decision: node_type=%s", route)
        if route not in {
            "OPERATIONAL_CASE",
            "SIMILARITY_SEARCH",
            "STRATEGY_ANALYSIS",
            "KPI_ANALYSIS",
        }:
            _graph_logger.warning(
                "[GRAPH_DEBUG] unexpected route value %r — falling back to SIMILARITY_SEARCH",
                route,
            )
            return "SIMILARITY_SEARCH"
        return str(route)

    def _route_operational_escalation(self, state: IncidentGraphState) -> str:
        # Closed case historical summaries skip the quality gate entirely.
        case_context = state.get("case_context")
        if self._extract_case_status(case_context) == "closed":
            return "CONTINUE"
        if self._escalation_controller.should_escalate_operational(dict(state)):
            return "ESCALATE"
        return "CONTINUE"

    def _route_strategy_escalation(self, state: IncidentGraphState) -> str:
        if self._escalation_controller.should_escalate_strategy(dict(state)):
            return "ESCALATE"
        return "CONTINUE"

    def _resolve_country(self, state: IncidentGraphState) -> str | None:
        classification = state.get("classification")
        if classification is None:
            return None
        if isinstance(classification, dict):
            classification = IntentClassificationResult.model_validate(classification)
        if classification.scope == "GLOBAL":
            return None
        question = str(state.get("question") or "")
        marker = "country:"
        marker_index = question.lower().find(marker)
        if marker_index < 0:
            return None
        trailing = question[marker_index + len(marker) :].strip()
        if not trailing:
            return None
        return trailing.split()[0].strip(",.;")

    @staticmethod
    def _extract_case_status(case_context: dict | None) -> str | None:
        """Extract the case status string from a case_context document.

        Supports two document shapes:
        - Nested:  case_context["case"]["status"]   (seeded/stored documents)
        - Flat:    case_context["status"]            (legacy or test fixtures)
        """
        if not isinstance(case_context, dict):
            return None
        nested = case_context.get("case")
        if isinstance(nested, dict):
            status = nested.get("status")
            if isinstance(status, str) and status.strip():
                return status.strip().lower()
        flat = case_context.get("status")
        if isinstance(flat, str) and flat.strip():
            return flat.strip().lower()
        return None


__all__ = ["IncidentGraphState", "UnifiedIncidentGraph"]
