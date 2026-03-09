from backend.ai.model_policy import ModelPolicy


class MockSettings:
    MODEL_INTENT_CLASSIFIER = "intent-model"
    MODEL_OPERATIONAL = "operational-model"
    MODEL_OPERATIONAL_PREMIUM = "operational-premium"
    MODEL_STRATEGY = "operational-model"
    MODEL_STRATEGY_PREMIUM = "operational-premium"


def test_resolve_model_operational_default() -> None:
    policy = ModelPolicy(MockSettings())
    assert policy.resolve_model("operational", {}) == "operational-model"


def test_resolve_model_operational_premium_when_escalated() -> None:
    policy = ModelPolicy(MockSettings())
    result = policy.resolve_model("operational", {"operational_escalated": True})
    assert result == "operational-premium"


def test_resolve_model_strategy_default() -> None:
    policy = ModelPolicy(MockSettings())
    assert policy.resolve_model("strategy", {}) == "operational-model"


def test_resolve_model_strategy_premium_when_escalated() -> None:
    policy = ModelPolicy(MockSettings())
    result = policy.resolve_model("strategy", {"strategy_escalated": True})
    assert result == "operational-premium"


def test_resolve_model_intent_fallback() -> None:
    policy = ModelPolicy(MockSettings())
    assert policy.resolve_model("intent", {}) == "intent-model"
    assert policy.resolve_model("unknown_node", {}) == "intent-model"


def test_model_policy_reads_from_settings() -> None:
    policy = ModelPolicy(MockSettings())
    assert policy._intent_default == "intent-model"
    assert policy._operational_default == "operational-model"
    assert policy._operational_premium == "operational-premium"
