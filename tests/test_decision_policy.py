from hydroseason._decision_policy import (
    DECISION_POLICY,
    decide_regime,
)


def test_decision_policy_constant():
    assert DECISION_POLICY == "hydroseason_0_2_0"


def test_timing_recurrence_seasonal_routes_to_per_year_detection():
    decision = decide_regime(classification="seasonal", status="ok")

    assert decision.regime == "seasonal"
    assert decision.route == "per_year_detection"
    assert decision.timing_evidence == "supported"
    assert decision.policy == "hydroseason_0_2_0"


def test_timing_recurrence_aseasonal_routes_to_events():
    decision = decide_regime(classification="aseasonal", status="ok")

    assert decision.regime == "aseasonal"
    assert decision.route == "event_characterisation"
    assert decision.timing_evidence == "unsupported"
    assert decision.policy == "hydroseason_0_2_0"


def test_timing_recurrence_never_emits_marginal_and_keeps_insufficiency():
    decision = decide_regime(classification=None, status="insufficient_record")

    assert decision.regime == "insufficient_record"
    assert decision.route == "insufficient_record"
    assert decision.timing_evidence == "insufficient"
    assert decision.policy == "hydroseason_0_2_0"
