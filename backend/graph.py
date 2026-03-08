"""CoSolve graph compilation — wires nodes and edges, nothing else.

Topology is identical to UnifiedIncidentGraph.__init__ (now deprecated).
No business logic, no LLM calls, no instantiation except the StateGraph builder.
"""
from langgraph.graph import StateGraph

from backend.state import IncidentGraphState
from backend.workflow.nodes.start_node import start_node
from backend.workflow.nodes.context_node import context_node
from backend.workflow.nodes.intent_classification_node import intent_classification_node
from backend.workflow.nodes.question_readiness_node import question_readiness_node
from backend.workflow.nodes.router_node import router_node
from backend.workflow.nodes.operational_node import operational_node
from backend.workflow.nodes.operational_reflection_node import operational_reflection_node
from backend.workflow.nodes.operational_escalation_node import operational_escalation_node
from backend.workflow.nodes.similarity_node import similarity_node
from backend.workflow.nodes.similarity_reflection_node import similarity_reflection_node
from backend.workflow.nodes.strategy_node import strategy_node
from backend.workflow.nodes.strategy_reflection_node import strategy_reflection_node
from backend.workflow.nodes.strategy_escalation_node import strategy_escalation_node
from backend.workflow.nodes.kpi_node import kpi_node
from backend.workflow.nodes.kpi_reflection_node import kpi_reflection_node
from backend.workflow.nodes.response_formatter_node import response_formatter_node
from backend.workflow.nodes.end_node import end_node
from backend.workflow.routing import (
    route_intent,
    route_question_readiness,
    route_operational_escalation,
    route_strategy_escalation,
)


def build_graph():
    graph = StateGraph(IncidentGraphState)

    # Nodes
    graph.add_node("start_node", start_node)
    graph.add_node("context_node", context_node)
    graph.add_node("intent_classification_node", intent_classification_node)
    graph.add_node("question_readiness_node", question_readiness_node)
    graph.add_node("router_node", router_node)
    graph.add_node("operational_node", operational_node)
    graph.add_node("operational_reflection_node", operational_reflection_node)
    graph.add_node("operational_escalation_node", operational_escalation_node)
    graph.add_node("similarity_node", similarity_node)
    graph.add_node("similarity_reflection_node", similarity_reflection_node)
    graph.add_node("strategy_node", strategy_node)
    graph.add_node("strategy_reflection_node", strategy_reflection_node)
    graph.add_node("strategy_escalation_node", strategy_escalation_node)
    graph.add_node("kpi_node", kpi_node)
    graph.add_node("kpi_reflection_node", kpi_reflection_node)
    graph.add_node("response_formatter_node", response_formatter_node)
    graph.add_node("end_node", end_node)

    # Entry and finish
    graph.set_entry_point("start_node")
    graph.set_finish_point("end_node")

    # Edges — topology unchanged from UnifiedIncidentGraph
    graph.add_edge("start_node", "context_node")
    graph.add_edge("context_node", "intent_classification_node")
    graph.add_edge("intent_classification_node", "question_readiness_node")

    graph.add_conditional_edges(
        "question_readiness_node",
        route_question_readiness,
        {
            "READY": "router_node",
            "NOT_READY": "response_formatter_node",
        },
    )

    graph.add_conditional_edges(
        "router_node",
        route_intent,
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
        route_operational_escalation,
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
        route_strategy_escalation,
        {
            "ESCALATE": "strategy_escalation_node",
            "CONTINUE": "response_formatter_node",
        },
    )
    graph.add_edge("strategy_escalation_node", "strategy_reflection_node")

    graph.add_edge("kpi_node", "kpi_reflection_node")
    graph.add_edge("kpi_reflection_node", "response_formatter_node")

    graph.add_edge("response_formatter_node", "end_node")

    return graph.compile()


compiled_graph = build_graph()
