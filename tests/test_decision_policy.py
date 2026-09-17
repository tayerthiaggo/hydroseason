from hydroseason._decision_policy import (
    DECISION_POLICY,
    decide_regime,
)


def test_decision_policy_constant():
    assert DECISION_POLICY == "hydroseason_0_2_0"


def test_timing_recurrence_seasonal_routes_to_per_year_detection():
    decision = decide_regime(
        classification="seasonal", status="ok", reason="peak_and_trough_recur"
    )

    assert decision.regime == "seasonal"
    assert decision.route == "per_year_detection"
    assert decision.supports_per_year_boundaries is True
    assert decision.supports_fixed_window is False
    assert decision.timing_evidence == "supported"
    assert decision.policy == "hydroseason_0_2_0"
    assert decision.implementation_policy == "hydroseason_0_2_0"


def test_timing_recurrence_aseasonal_routes_to_events():
    decision = decide_regime(
        classification="aseasonal",
        status="ok",
        reason="peak_and_trough_uniformity_not_rejected",
    )

    assert decision.regime == "aseasonal"
    assert decision.route == "event_characterisation"
    assert decision.supports_per_year_boundaries is False
    assert decision.supports_fixed_window is False
    assert decision.timing_evidence == "unsupported"
    assert decision.policy == "hydroseason_0_2_0"


def test_timing_recurrence_never_emits_marginal_and_keeps_insufficiency():
    decision = decide_regime(
        classification=None, status="insufficient_record", reason="trend_unavailable"
    )

    assert decision.regime == "insufficient_record"
    assert decision.route == "insufficient_record"
    assert decision.supports_per_year_boundaries is False
    assert decision.supports_fixed_window is False
    assert decision.timing_evidence == "insufficient"
    assert "trend_unavailable" in decision.reason
    assert decision.policy == "hydroseason_0_2_0"
