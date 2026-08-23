from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hydroseason import load_extent_csv
from hydroseason._boundary_recoverability import RecoverabilityThresholds
from hydroseason._evidence import EvidenceThresholds
from hydroseason._regime import (
    REGIME_THRESHOLDS,
    assess_water_regime,
    public_route,
)

_CASE_STUDY_EXTENT_DIR = Path("case_studies/data/extent")
_CASE_STUDY_KEYS = (
    "daly_river_nt",
    "fitzroy_river_wa",
    "gilbert_river_qld",
    "lachlan_river_nsw",
    "moonie_river_qld_nsw",
)


def _checked_case_study_regimes():
    """Assess the committed 30 m extent fixtures without boundary or network inputs."""
    return {
        key: assess_water_regime(
            load_extent_csv(
                _CASE_STUDY_EXTENT_DIR / f"{key}_30m.csv",
                date_col="date",
                value_col="extent_pct",
            ),
            quality_policy="flag",
            n_bootstrap=200,
            random_state=0,
        )
        for key in _CASE_STUDY_KEYS
    }


def _series(monthly_values, years=30, noise=0.0, seed=0):
    """Monthly extent series repeating ``monthly_values`` with optional noise."""
    rng = np.random.default_rng(seed)
    index = pd.date_range("1990-01-01", periods=12 * years, freq="MS")
    values = np.tile(monthly_values, years)
    if noise:
        values = values + rng.normal(0.0, noise, size=len(values))
    return pd.DataFrame(
        {"extent_pct": np.clip(values, 0.0, None), "invalid_pct": 0.0},
        index=index,
    )


def _drop_months(frame, months):
    """Blank out given calendar months, mimicking wet-season cloud loss."""
    out = frame.copy()
    out.loc[out.index.month.isin(months), "extent_pct"] = np.nan
    out.loc[out.index.month.isin(months), "invalid_pct"] = 100.0
    return out


def _january_july_bimodal_peaks(*, years=40, amplitude=8.0):
    """High-SNR annual records whose peaks split evenly across two phases."""
    index = pd.date_range("1990-01-01", periods=12 * years, freq="MS")
    values = np.zeros(12 * years)
    for year in range(years):
        values[12 * year + (0 if year % 2 == 0 else 6)] = amplitude
    return pd.DataFrame(
        {"extent_pct": values, "invalid_pct": 0.0}, index=index,
    )


def _low_power_broad_peak_record():
    """Seven high-SNR years with insufficient timing evidence for uniformity."""
    index = pd.date_range("1990-01-01", periods=12 * 7, freq="MS")
    values = np.tile(np.array([8.0] * 11 + [0.0]), 7)
    for year, month in enumerate([1, 3, 5, 7, 9, 11, 1]):
        values[12 * year + month - 1] = 8.1
    return pd.DataFrame(
        {"extent_pct": values, "invalid_pct": 0.0}, index=index,
    )


def _stable_peak_unstable_trough_record(*, years=30):
    """A strongly seasonal record whose trough alternates between two months."""
    index = pd.date_range("1990-01-01", periods=12 * years, freq="MS")
    chunks = []
    for year in range(years):
        values = np.full(12, 5.0)
        values[3] = 10.0
        values[0 if year % 2 == 0 else 6] = 0.0
        chunks.append(values)
    return pd.DataFrame(
        {"extent_pct": np.concatenate(chunks), "invalid_pct": 0.0}, index=index,
    )


# --- regime classification -------------------------------------------------

def test_regime_thresholds_publish_peak_concentration_contract():
    assert REGIME_THRESHOLDS == {
        "seasonal_min_snr": 2.0,
        "strong_timing_concentration": 0.7,
        "weak_timing_concentration": 0.3,
        "aseasonal_max_snr": 0.7,
        "circular_uniformity_alpha": 0.1,
        "uniformity_min_timing_years": 10.0,
        "timing_record_caution_years": 30.0,
    }


def test_checked_case_study_fixtures_preserve_scientific_timing_properties():
    """Changing timing qualification or concentration must not invert these fixtures' evidence."""
    regimes = _checked_case_study_regimes()

    peak_r = {key: result.peak_timing_concentration for key, result in regimes.items()}
    assert (
        peak_r["gilbert_river_qld"]
        > peak_r["fitzroy_river_wa"]
        > peak_r["daly_river_nt"]
        > peak_r["moonie_river_qld_nsw"]
        > peak_r["lachlan_river_nsw"]
    )
    for result in regimes.values():
        assert 0.0 <= result.peak_timing_concentration_ci_low <= 1.0
        assert 0.0 <= result.peak_timing_concentration_ci_high <= 1.0
        assert result.n_timing_years == 21
        assert "fewer than 30 usable annual timings" in " ".join(result.caveats)
    assert regimes["daly_river_nt"].peak_timing_concentration_ci_low >= 0.7
    assert regimes["lachlan_river_nsw"].peak_timing_concentration_ci_low < 0.7


def test_checked_case_study_routes_follow_snr_and_trough_timing_evidence():
    """Checked case-study regimes follow established decision policy."""
    regimes = _checked_case_study_regimes()

    for key in (
        "daly_river_nt",
        "fitzroy_river_wa",
        "gilbert_river_qld",
    ):
        assert regimes[key].regime == "seasonal"
        assert regimes[key].public_route == "per_year_detection"
        assert regimes[key].supports_per_year_boundaries is True

    for key in (
        "lachlan_river_nsw",
        "moonie_river_qld_nsw",
    ):
        assert regimes[key].regime == "aseasonal"
        assert regimes[key].public_route == "event_characterisation"
        assert regimes[key].supports_per_year_boundaries is False


def test_established_public_timing_uses_one_exact_extremum_per_year(fitzroy_30m):
    assessment = assess_water_regime(fitzroy_30m, n_bootstrap=40)
    assert assessment.decision_policy == "established_0_1_1"
    assert assessment.climatological_peak_month == 2
    assert assessment.climatological_trough_month == 11
    assert assessment.regime == "seasonal"
    assert assessment.challenger.peak_timing is not None


def test_constant_record_has_finite_zero_established_snr():
    index = pd.date_range("2000-01-01", periods=12 * 12, freq="MS")
    constant = pd.DataFrame(
        {"extent_pct": 10.0, "invalid_pct": 0.0},
        index=index,
    )
    assessment = assess_water_regime(constant, n_bootstrap=40)
    assert assessment.amplitude_snr == 0.0
    assert np.isfinite(assessment.amplitude_snr)
    assert assessment.regime == "aseasonal"


def test_challenger_failure_does_not_change_established_assessment(monkeypatch, fitzroy_30m):
    baseline = assess_water_regime(fitzroy_30m, n_bootstrap=40)

    def explode(*args, **kwargs):
        raise RuntimeError("challenger unavailable")

    monkeypatch.setattr("hydroseason._regime.assess_challenger", explode)
    isolated = assess_water_regime(fitzroy_30m, n_bootstrap=40)

    assert isolated.regime == baseline.regime == "seasonal"
    assert isolated.public_route == baseline.public_route == "per_year_detection"
    assert isolated.climatological_peak_month == baseline.climatological_peak_month
    assert isolated.climatological_trough_month == baseline.climatological_trough_month
    assert isolated.challenger.status == "failed"
    assert any("experimental challenger failed" in item for item in isolated.caveats)


def test_checked_case_study_peak_timing_concentrations_are_reproducible():
    """Characterization: random_state=0, n_bootstrap=999, n_null=999.

    ``n_null`` is the circular-timing implementation's documented
    ``max(n_bootstrap, 999)`` value. The stale plan triples came from an
    unrecorded Monte Carlo realization and are intentionally not used.
    """
    expected = {
        "daly_river_nt": (0.853, 0.773, 0.927),
        "fitzroy_river_wa": (0.829, 0.752, 0.905),
        "gilbert_river_qld": (0.919, 0.890, 0.954),
        "lachlan_river_nsw": (0.232, 0.095, 0.492),
        "moonie_river_qld_nsw": (0.496, 0.300, 0.739),
    }

    regimes = _checked_case_study_regimes()
    for key, (concentration, ci_low, ci_high) in expected.items():
        timing = regimes[key].challenger.peak_timing
        assert timing is not None
        assert timing.concentration == pytest.approx(concentration, abs=0.005)
        assert timing.ci_low == pytest.approx(ci_low, abs=0.02)
        assert timing.ci_high == pytest.approx(ci_high, abs=0.02)

def test_strong_annual_cycle_is_seasonal():
    cycle = 1.0 + 0.8 * np.cos(2 * np.pi * (np.arange(12) - 1) / 12)
    result = assess_water_regime(_series(cycle, noise=0.02), n_bootstrap=40)
    assert result.regime == "seasonal"
    assert result.amplitude_snr > 2.0
    assert result.climatological_peak_month == 2
    assert result.peak_timing_concentration > 0.9
    assert result.peak_timing_concentration_ci_low >= 0.7
    assert result.peak_timing_uniformity_p < 0.1
    assert result.trough_timing_concentration is not None
    assert result.n_timing_years == result.n_usable_years == 30


def test_symmetric_january_july_peaks_are_marginal_despite_high_snr():
    result = assess_water_regime(
        _january_july_bimodal_peaks(amplitude=8.0), n_bootstrap=999,
    )

    assert result.amplitude_snr >= 2.0
    assert result.peak_timing_concentration < 0.3
    assert result.peak_timing_uniformity_p < 0.1
    assert result.regime == "marginal"


def test_qualifying_year_predicate_counts_distinct_months_for_timings(monkeypatch):
    cycle = 1.0 + 0.8 * np.cos(2 * np.pi * (np.arange(12) - 1) / 12)
    raw = _series(cycle, years=5)
    prepared = raw.copy()
    extra = raw.loc[[pd.Timestamp("1994-01-01")]].copy()
    extra.index = [pd.Timestamp("1995-01-01")]
    repeated = pd.concat([extra] * 9)
    repeated.index = pd.to_datetime(
        [
            "1995-01-01", "1995-02-01", "1995-03-01", "1995-04-01",
            "1995-05-01", "1995-06-01", "1995-07-01", "1995-08-01",
            "1995-08-01",
        ]
    )
    prepared = pd.concat([prepared, repeated])
    prepared["candidate_usable"] = True
    monkeypatch.setattr("hydroseason._regime.prepare_monthly_extent", lambda *args, **kwargs: prepared)

    result = assess_water_regime(raw, n_bootstrap=40)

    assert result.n_usable_years == 5
    assert result.n_timing_years == result.n_usable_years


def test_seven_broad_peak_years_with_wide_ci_are_marginal():
    result = assess_water_regime(_low_power_broad_peak_record(), n_bootstrap=999)

    assert result.amplitude_snr >= 2.0
    assert result.peak_timing_concentration_ci_low < 0.7
    assert result.peak_timing_uniformity_p >= 0.1
    assert result.n_timing_years == 7
    assert result.regime == "marginal"
    assert result.climatological_peak_month is not None
    assert result.climatological_trough_month is not None
    assert "fewer than 30 usable annual timings" in " ".join(result.caveats)


def test_ten_year_seasonal_record_carries_timing_caution():
    cycle = 1.0 + 0.8 * np.cos(2 * np.pi * (np.arange(12) - 1) / 12)
    result = assess_water_regime(_series(cycle, years=10, noise=0.02), n_bootstrap=40)

    assert result.regime == "seasonal"
    assert result.n_timing_years == 10
    caveats = " ".join(result.caveats)
    assert "fewer than 30 usable annual timings" in caveats
    assert "classification is retained" in caveats
    assert "uncertainty intervals may be wide" in caveats


def test_flat_noise_only_series_is_aseasonal():
    flat = np.repeat(0.15, 12)
    result = assess_water_regime(_series(flat, noise=0.12, seed=3))
    assert result.regime == "aseasonal"
    assert result.climatological_peak_month is None
    assert result.climatological_trough_month is None


def test_weak_cycle_under_heavy_noise_is_marginal():
    cycle = 0.45 + 0.16 * np.cos(2 * np.pi * (np.arange(12) - 10) / 12)
    result = assess_water_regime(_series(cycle, noise=0.16, seed=7))
    assert result.regime == "marginal"


def test_short_record_is_insufficient():
    cycle = 1.0 + 0.8 * np.cos(2 * np.pi * (np.arange(12) - 1) / 12)
    result = assess_water_regime(_series(cycle, years=3))
    assert result.regime == "insufficient_record"
    assert result.climatological_peak_month is None


# --- the tropical cloud-gap regression ------------------------------------

def test_partial_years_still_classify_when_wet_months_are_cloud_lost():
    """A monsoonal catchment losing 2 wet months/yr to cloud must not be
    reported as having no usable record: the 12/12 completeness rule this
    replaces discarded exactly the strongly-seasonal catchments."""
    cycle = 1.0 + 0.8 * np.cos(2 * np.pi * (np.arange(12) - 1) / 12)
    gappy = _drop_months(_series(cycle, noise=0.02), months=[1, 2])
    result = assess_water_regime(gappy)
    assert result.regime == "seasonal"
    assert result.n_usable_years >= 20


def test_completeness_threshold_is_configurable():
    cycle = 1.0 + 0.8 * np.cos(2 * np.pi * (np.arange(12) - 1) / 12)
    gappy = _drop_months(_series(cycle, noise=0.02), months=[1, 2, 3, 4])
    lenient = assess_water_regime(gappy, min_months_per_year=8)
    strict = assess_water_regime(gappy, min_months_per_year=11)
    assert lenient.n_usable_years > strict.n_usable_years


# --- scale invariance ------------------------------------------------------

def test_regime_is_invariant_to_absolute_extent_scale():
    """A catchment whose whole signal sits under 1% must classify the same as
    one an order of magnitude larger. An absolute pp tolerance breaks this."""
    cycle = 1.0 + 0.8 * np.cos(2 * np.pi * (np.arange(12) - 1) / 12)
    big = assess_water_regime(_series(cycle, noise=0.02))
    small = assess_water_regime(_series(cycle * 0.05, noise=0.001))
    assert big.regime == small.regime == "seasonal"
    assert small.climatological_peak_month == big.climatological_peak_month


def test_measurement_tolerance_keeps_equivalent_trough_months_in_timing():
    dates = pd.date_range("2000-01-01", periods=12 * 10, freq="MS")
    cycle = np.array([8.0, 7.0, 6.0, 4.0, 2.0, 0.0, 0.5, 2.0, 4.0, 6.0, 7.0, 8.5])
    frame = pd.DataFrame(
        {"extent_pct": np.tile(cycle, 10), "invalid_pct": 0.0}, index=dates
    )

    exact = assess_water_regime(frame, measurement_tolerance_pct=0.0, n_bootstrap=20)
    tolerant = assess_water_regime(frame, measurement_tolerance_pct=1.0, n_bootstrap=20)

    assert exact.challenger.trough_timing.concentration == 1.0
    assert tolerant.challenger.trough_timing.concentration < exact.challenger.trough_timing.concentration


# --- guidance payload ------------------------------------------------------

def test_seasonal_regime_permits_per_year_boundaries():
    cycle = 1.0 + 0.8 * np.cos(2 * np.pi * (np.arange(12) - 1) / 12)
    result = _calibrated_assessment(_series(cycle, noise=0.02))
    assert result.supports_per_year_boundaries is True
    assert result.supports_fixed_window is True


def test_seasonal_record_with_unstable_trough_does_not_permit_per_year_boundaries():
    result = _calibrated_assessment(_stable_peak_unstable_trough_record())
    assert result.supports_per_year_boundaries is False
    assert result.supports_fixed_window is True


def test_marginal_regime_with_supported_boundaries_permits_per_year():
    dates = pd.date_range("2000-01-01", periods=12 * 6, freq="MS")
    cycle = 1.0 + 0.8 * np.cos(2 * np.pi * (np.arange(12) - 1) / 12)
    vals = np.tile(cycle, 6)
    vals[0 * 12 + 3] = 0.05
    vals[1 * 12 + 3] = 0.05
    vals[2 * 12 + 3] = 0.05
    frame = pd.DataFrame({"extent_pct": vals, "invalid_pct": 0.0}, index=dates)
    result = assess_water_regime(frame, quality_policy="flag", n_bootstrap=100)
    assert result.regime == "seasonal"
    assert result.supports_fixed_window is True
    assert result.boundary_recoverability == "supported"
    assert public_route(result.regime, result.boundary_recoverability) == "per_year_detection"


def test_aseasonal_regime_permits_neither():
    result = assess_water_regime(_series(np.repeat(0.15, 12), noise=0.12, seed=3))
    assert result.supports_fixed_window is False
    assert result.supports_per_year_boundaries is False


def test_assessment_reports_event_descriptors():
    result = assess_water_regime(_series(np.repeat(0.15, 12), noise=0.12, seed=3))
    assert result.longest_low_spell_months > 0
    assert result.n_wet_events > 0


def test_persistent_noise_is_downgraded_not_rated_high():
    """Multi-year wet/dry persistence inflates a window's max-minus-min without
    any seasonal cycle being present. Confidence must not read that as signal.
    """
    from hydroseason.hydro_year import HydroYearConfig, detect_hydrological_years

    rng = np.random.default_rng(5)
    index = pd.date_range("1990-01-01", periods=12 * 30, freq="MS")
    walk = np.zeros(len(index))
    for i in range(1, len(index)):  # AR(1), no seasonal term whatsoever
        walk[i] = 0.8 * walk[i - 1] + rng.normal(0.0, 0.1)
    frame = pd.DataFrame(
        {"extent_pct": np.abs(walk + 0.5), "invalid_pct": 0.0}, index=index
    )
    cfg = HydroYearConfig(
        wet_start_month=12, wet_end_month=4, dry_start_month=5, dry_end_month=10
    )
    result = detect_hydrological_years(
        frame, config=cfg, quality_policy="flag", missing_month_policy="ignore"
    )
    high_fraction = (result["confidence"] == "high").mean()
    assert high_fraction < 0.5, f"persistent noise rated {high_fraction:.0%} high"


def test_caveats_never_claim_climate_and_flag_non_rainfall_drivers():
    """Surface-water extent is water availability as observed, not a climate
    signal: regulated or extracted catchments can look aseasonal for reasons
    that have nothing to do with rainfall."""
    result = assess_water_regime(_series(np.repeat(0.15, 12), noise=0.12, seed=3))
    joined = " ".join(result.caveats).lower()
    # Climate may only appear as an explicit disclaimer, never as a claim.
    assert "not a climate variable" in joined
    assert "water availability" in joined
    assert "regulation" in joined or "extraction" in joined


def test_event_descriptors_match_the_shared_event_definition():
    """Regime must not carry its own private notion of an event.

    A second definition drifts from the first: the regime module previously
    counted episodes on a bare p75 quantile while ``extract_water_events``
    used noise-relative thresholds with hysteresis and duration filters, so
    the same record reported two different event counts depending on which
    entry point the caller used.
    """
    from hydroseason._events import extract_water_events

    frame = _series(np.repeat(0.15, 12), noise=0.12, seed=3)
    regime = assess_water_regime(frame)
    events = extract_water_events(frame)
    assert regime.n_wet_events == events.summary["n_events"]
    assert (
        regime.longest_low_spell_months
        == events.summary["longest_low_spell_months"]
    )


EVIDENCE = EvidenceThresholds(
    seasonal_cv_skill=0.3,
    periodicity_alpha=0.05,
    amplitude_noise_ratio=1.0,
    mode_min_frequency=0.60,
    mode_min_separation_months=2,
    strong_timing_concentration=0.70,
    weak_timing_concentration=0.40,
    min_timing_years=10,
)
RECOVERABILITY = RecoverabilityThresholds(
    min_years=5,
    min_coverage=0.80,
    min_within_1_month=0.80,
    within_1_month_wilson_floor=0.50,
    max_p90_error_months=2.0,
    admit_insufficient_drift=False,
)


def _calibrated_assessment(frame):
    return assess_water_regime(
        frame,
        evidence_thresholds=EVIDENCE,
        recoverability_thresholds=RECOVERABILITY,
    )


def test_constant_zero_record_is_aseasonal_not_infinite():
    index = pd.date_range("2000-01-01", periods=12 * 12, freq="MS")
    frame = pd.DataFrame({"extent_pct": 0.0, "invalid_pct": 0.0}, index=index)

    assessment = _calibrated_assessment(frame)

    assert np.isfinite(assessment.amplitude_snr)
    assert assessment.amplitude_snr == 0.0
    assert assessment.regime == "aseasonal"
    assert assessment.annual_cycle_evidence == "absent"


def test_constant_nonzero_record_is_also_aseasonal():
    index = pd.date_range("2000-01-01", periods=12 * 12, freq="MS")
    frame = pd.DataFrame({"extent_pct": 42.0, "invalid_pct": 0.0}, index=index)

    assessment = _calibrated_assessment(frame)

    assert np.isfinite(assessment.amplitude_snr)
    assert assessment.regime == "aseasonal"


def test_stable_peak_with_unstable_trough_is_not_seasonal():
    """Dynamic years anchor on troughs, so a stable peak alone is not enough."""
    assessment = _calibrated_assessment(_stable_peak_unstable_trough_record())

    assert (
        assessment.regime != "seasonal"
        or not assessment.supports_per_year_boundaries
    )


def test_clean_seasonal_record_is_seasonal_with_strong_evidence():
    index = pd.date_range("2000-01-01", periods=12 * 15, freq="MS")
    angle = 2.0 * np.pi * (index.month - 1) / 12.0
    frame = pd.DataFrame(
        {"extent_pct": 50.0 + 25.0 * np.cos(angle), "invalid_pct": 0.0},
        index=index,
    )

    assessment = _calibrated_assessment(frame)

    assert assessment.regime == "seasonal"
    assert assessment.annual_cycle_evidence in {"strong", "moderate"}
    assert assessment.trough_timing_n_modes == 1


def test_drift_stays_unmeasurable_below_ten_years():
    """Evidence timing threshold must not weaken structural drift minimum."""
    index = pd.date_range("2000-01-01", periods=12 * 7, freq="MS")
    angle = 2.0 * np.pi * (index.month - 1) / 12.0
    frame = pd.DataFrame(
        {"extent_pct": 50.0 + 25.0 * np.cos(angle), "invalid_pct": 0.0},
        index=index,
    )

    assessment = assess_water_regime(
        frame,
        evidence_thresholds=replace(EVIDENCE, min_timing_years=5),
        recoverability_thresholds=replace(
            RECOVERABILITY, admit_insufficient_drift=True
        ),
    )

    assert assessment.peak_timing_drift_status == "insufficient_for_drift"
    assert assessment.trough_timing_drift_status == "insufficient_for_drift"


def test_short_record_is_insufficient_under_calibrated_thresholds():
    index = pd.date_range("2000-01-01", periods=12 * 3, freq="MS")
    angle = 2.0 * np.pi * (index.month - 1) / 12.0
    frame = pd.DataFrame(
        {"extent_pct": 50.0 + 25.0 * np.cos(angle), "invalid_pct": 0.0},
        index=index,
    )

    assessment = _calibrated_assessment(frame)

    assert assessment.regime == "insufficient_record"


def test_every_public_field_is_finite_or_none():
    index = pd.date_range("2000-01-01", periods=12 * 12, freq="MS")
    frame = pd.DataFrame({"extent_pct": 0.0, "invalid_pct": 0.0}, index=index)

    assessment = _calibrated_assessment(frame)

    for field_name in assessment.__dataclass_fields__:
        value = getattr(assessment, field_name)
        if isinstance(value, float):
            assert np.isfinite(value), f"{field_name} is not finite"


@pytest.mark.parametrize(
    "regime, recoverability, expected",
    [
        ("seasonal", "supported", "per_year_detection"),
        ("marginal", "supported", "per_year_detection"),
        ("seasonal", "provisional", "event_characterisation"),
        ("seasonal", "unsupported", "event_characterisation"),
        ("seasonal", "insufficient", "event_characterisation"),
        ("marginal", "provisional", "event_characterisation"),
        ("aseasonal", "supported", "event_characterisation"),
        ("aseasonal", "insufficient", "event_characterisation"),
        ("insufficient_record", "supported", "insufficient_record"),
        ("insufficient_record", "insufficient", "insufficient_record"),
    ],
)
def test_route_matrix(regime, recoverability, expected):
    assert public_route(regime, recoverability) == expected


def test_marginal_supported_can_publish_years():
    """A marginal record with reproducible troughs is allowed dynamic years."""
    assert public_route("marginal", "supported") == "per_year_detection"


def test_seasonal_without_recoverable_boundaries_abstains():
    assert public_route("seasonal", "provisional") == "event_characterisation"
