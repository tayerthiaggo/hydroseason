from hydroseason._circular_timing import CircularTimingSummary
from hydroseason._decision_policy import decide_established


def timing(*, concentration=0.9, ci_low=0.8, p=0.01, n=20):
    return CircularTimingSummary(concentration, ci_low, 0.95, 1.0, p, n)


def test_seasonal_and_reproducible_trough_routes_per_year():
    result = decide_established(
        n_usable_years=20,
        amplitude_snr=2.0,
        peak_timing=timing(ci_low=0.70),
        trough_timing=timing(ci_low=0.70),
    )
    assert (result.regime, result.route) == ("seasonal", "per_year_detection")


def test_seasonal_with_variable_trough_routes_per_year_detection():
    result = decide_established(
        n_usable_years=20,
        amplitude_snr=2.0,
        peak_timing=timing(ci_low=0.70),
        trough_timing=timing(ci_low=0.69),
    )
    assert (result.regime, result.route) == ("seasonal", "per_year_detection")


def test_low_snr_precedes_uniformity_and_routes_events():
    result = decide_established(
        n_usable_years=20,
        amplitude_snr=0.699,
        peak_timing=timing(p=0.001),
        trough_timing=timing(),
    )
    assert (result.regime, result.route) == ("aseasonal", "event_characterisation")


def test_uniform_peak_timing_is_aseasonal_only_at_ten_timings():
    nine = decide_established(
        n_usable_years=9,
        amplitude_snr=1.0,
        peak_timing=timing(p=0.10, n=9),
        trough_timing=timing(n=9),
    )
    ten = decide_established(
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
    result = decide_established(
        n_usable_years=20,
        amplitude_snr=1.0,
        peak_timing=timing(concentration=0.30, ci_low=0.2, p=0.099),
        trough_timing=timing(concentration=0.30, ci_low=0.2, p=0.099),
    )
    assert (result.regime, result.route) == ("marginal", "per_year_detection")
    assert result.supports_per_year_boundaries is True


def test_four_usable_years_is_insufficient():
    result = decide_established(
        n_usable_years=4,
        amplitude_snr=100.0,
        peak_timing=timing(),
        trough_timing=timing(),
    )
    assert (result.regime, result.route) == ("insufficient_record", "insufficient_record")
