from backend.ai.escalation_controller import EscalationController
from backend.workflow.models import ReflectionResult


def test_should_escalate_operational_true_when_needed_and_not_escalated() -> None:
    controller = EscalationController()
    state = {
        "operational_reflection": ReflectionResult(
            quality_score=0.35,
            needs_escalation=True,
            reasoning_feedback="Need stronger grounding",
        ),
        "operational_escalated": False,
    }
    assert controller.should_escalate_operational(state) is True


def test_should_escalate_operational_false_when_already_escalated() -> None:
    controller = EscalationController()
    state = {
        "operational_reflection": ReflectionResult(
            quality_score=0.35,
            needs_escalation=True,
            reasoning_feedback="Need stronger grounding",
        ),
        "operational_escalated": True,
    }
    assert controller.should_escalate_operational(state) is False


def test_should_escalate_operational_false_when_no_reflection() -> None:
    controller = EscalationController()
    state = {"operational_escalated": False}
    assert controller.should_escalate_operational(state) is False


def test_should_escalate_operational_false_when_escalation_not_needed() -> None:
    controller = EscalationController()
    state = {
        "operational_reflection": ReflectionResult(
            quality_score=0.85,
            needs_escalation=False,
            reasoning_feedback="Good quality output.",
        ),
        "operational_escalated": False,
    }
    assert controller.should_escalate_operational(state) is False


def test_should_escalate_strategy_true_when_needed() -> None:
    controller = EscalationController()
    state = {
        "strategy_reflection": ReflectionResult(
            quality_score=0.4,
            needs_escalation=True,
            reasoning_feedback="Weak strategy draft.",
        ),
        "strategy_escalated": False,
    }
    assert controller.should_escalate_strategy(state) is True


def test_should_escalate_strategy_false_when_already_escalated() -> None:
    controller = EscalationController()
    state = {
        "strategy_reflection": ReflectionResult(
            quality_score=0.4,
            needs_escalation=True,
            reasoning_feedback="Weak strategy draft.",
        ),
        "strategy_escalated": True,
    }
    assert controller.should_escalate_strategy(state) is False


def test_accepts_dict_reflection_as_well() -> None:
    controller = EscalationController()
    state = {
        "operational_reflection": {"needs_escalation": True},
        "operational_escalated": False,
    }
    assert controller.should_escalate_operational(state) is True