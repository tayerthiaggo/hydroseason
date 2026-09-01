from hydroseason._circular_timing import AnnualTimingSummary
from hydroseason._decision_policy import decide_established


def timing(*, concentration=0.9, ci_low=0.8, p=0.01, n=20):
    return AnnualTimingSummary(concentration, ci_low, 0.95, 1.0, p, n, 2)


def decide(**kwargs):
    peak_timing = kwargs.pop("peak_timing", timing())
    trough_timing = kwargs.pop("trough_timing", timing())
    return decide_established(
        n_peak_timing_years=peak_timing.n_years,
        n_trough_timing_years=trough_timing.n_years,
        min_informative_years=7,
        peak_timing=peak_timing,
        trough_timing=trough_timing,
        **kwargs,
    )


def test_seasonal_and_reproducible_trough_routes_per_year():
    result = decide(
        n_usable_years=20,
        amplitude_snr=2.0,
        peak_timing=timing(ci_low=0.70),
        trough_timing=timing(ci_low=0.70),
    )
    assert (result.regime, result.route) == ("seasonal", "per_year_detection")


def test_seasonal_with_variable_trough_routes_per_year_detection():
    result = decide(
        n_usable_years=20,
        amplitude_snr=2.0,
        peak_timing=timing(ci_low=0.70),
        trough_timing=timing(ci_low=0.69),
    )
    assert (result.regime, result.route) == ("seasonal", "per_year_detection")


def test_low_snr_precedes_uniformity_and_routes_events():
    result = decide(
        n_usable_years=20,
        amplitude_snr=0.699,
        peak_timing=timing(p=0.001),
        trough_timing=timing(),
    )
    assert (result.regime, result.route) == ("aseasonal", "event_characterisation")
    assert result.timing_evidence == "unsupported"


def test_unsupported_timing_evidence_is_exactly_aseasonal_regime():
    scenarios = [
        dict(
            n_usable_years=20,
            amplitude_snr=0.699,
            peak_timing=timing(p=0.001),
            trough_timing=timing(),
        ),
        dict(
            n_usable_years=20,
            amplitude_snr=2.0,
            peak_timing=timing(ci_low=0.70),
            trough_timing=timing(ci_low=0.70),
        ),
        dict(
            n_usable_years=20,
            amplitude_snr=1.0,
            peak_timing=timing(concentration=0.30, ci_low=0.2, p=0.099),
            trough_timing=timing(concentration=0.30, ci_low=0.2, p=0.099),
        ),
        dict(
            n_usable_years=20,
            amplitude_snr=1.0,
            peak_timing=timing(n=3),
            trough_timing=timing(n=3),
        ),
    ]
    for scenario in scenarios:
        result = decide(**scenario)
        assert (result.timing_evidence == "unsupported") == (
            result.regime == "aseasonal"
        )


def test_uniform_peak_timing_is_aseasonal_only_at_ten_timings():
    nine = decide(
        n_usable_years=9,
        amplitude_snr=1.0,
        peak_timing=timing(p=0.10, n=9),
        trough_timing=timing(n=9),
    )
    ten = decide(
        n_usable_years=10,
        amplitude_snr=1.0,
        peak_timing=timing(p=0.10, n=10),
        trough_timing=timing(n=10),
    )
    assert nine.regime == "marginal"
    assert nine.route == "per_year_detection"
    assert ten.regime == "aseasonal"
    assert ten.route == "event_characterisation"


def test_marginal_routes_per_year_detection():
    result = decide(
        n_usable_years=20,
        amplitude_snr=1.0,
        peak_timing=timing(concentration=0.30, ci_low=0.2, p=0.099),
        trough_timing=timing(concentration=0.30, ci_low=0.2, p=0.099),
    )
    assert (result.regime, result.route) == ("marginal", "per_year_detection")
    assert result.supports_per_year_boundaries is True


def test_four_usable_years_is_insufficient():
    result = decide(
        n_usable_years=4,
        amplitude_snr=100.0,
        peak_timing=timing(),
        trough_timing=timing(),
    )
    assert (result.regime, result.route) == ("insufficient_record", "insufficient_record")


def test_candidate_route_requires_informative_peak_and_trough_years():
    result = decide_established(
        n_usable_years=20,
        amplitude_snr=2.0,
        peak_timing=timing(n=7),
        trough_timing=timing(n=6),
        n_peak_timing_years=7,
        n_trough_timing_years=6,
        min_informative_years=7,
    )

    assert result.regime == "seasonal"
    assert result.timing_evidence == "insufficient"
    assert result.route == "event_characterisation"


def test_candidate_contract_does_not_claim_public_promotion():
    result = decide(
        n_usable_years=20,
        amplitude_snr=2.0,
        peak_timing=timing(ci_low=0.70),
        trough_timing=timing(ci_low=0.70),
    )

    assert result.policy == "established_0_1_1"
    assert result.implementation_policy == "established_0_2_0"
    assert "candidate=established_0_2_0" in result.reason
    assert "authority=established_0_1_1" in result.reason
