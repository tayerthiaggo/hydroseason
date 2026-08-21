import hydroseason as hs


def test_public_surface_exports_evidence_primitives():
    expected_exports = [
        "candidate_weights",
        "equivalent_extremum_months",
        "AnnualTimingSummary",
        "summarise_annual_timing",
        "HarmonicSelection",
        "select_harmonic_order",
        "AmplitudeEvidence",
        "amplitude_evidence",
        "periodicity_p_value",
        "retained_modes",
        "PhaseDriftSummary",
        "phase_drift",
    ]
    for name in expected_exports:
        assert hasattr(hs, name), f"hydroseason is missing public export '{name}'"
        assert name in hs.__all__, f"'{name}' is missing from hydroseason.__all__"


def test_deprecated_helpers_remain_accessible():
    assert hasattr(hs, "fit_seasonal_harmonics") or hasattr(hs._seasonality, "fit_seasonal_harmonics")
    assert hasattr(hs, "assess_seasonal_pattern") or hasattr(hs._seasonality, "assess_seasonal_pattern")
