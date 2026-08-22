import hydroseason as hs


def test_evidence_primitives_stay_internal():
    """0.2.0 publishes evidence fields, not its implementation helpers."""
    internal_names = {
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
        "TimingDrift",
        "timing_drift",
        # Superseded names must not survive as accidental compatibility exports.
        "PhaseDriftSummary",
        "phase_drift",
        "assess_seasonal_pattern",
        "fit_seasonal_harmonics",
    }

    assert internal_names.isdisjoint(vars(hs))
    assert internal_names.isdisjoint(hs.__all__)
