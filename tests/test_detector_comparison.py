# tests/test_detector_comparison.py
"""Experimental promotion-gate harness comparing robust_extrema vs semi_markov.

This test is intentionally allowed to fail: real promotion of the semi-Markov
challenger requires untouched climate/sensor holdouts this repository does not
have (see docs/superpowers/specs/2026-07-15-transferable-hydrological-boundary-design.md
section 6.2). It is marked ``experimental`` so it never blocks release; robust
stays the shipped default regardless of the outcome printed here.
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hydroseason import DynamicHydroYearConfig, detect_dynamic_hydrological_years
from hydroseason._boundary_validation import align_events_by_interval, summarize_timing
from hydroseason._dynamic_year import (
    _find_robust_trough_opportunities,
    _find_semi_markov_trough_opportunities,
)
from hydroseason._state_input import prepare_monthly_extent
from tests.test_fitzroy_regression import _fitzroy_trough_truth

FIXTURES = Path(__file__).parent / "fixtures"

_BOOTSTRAP_SEED = 20260715
_N_BOOTSTRAP = 2000


def _fitzroy_inputs():
    monthly = pd.read_csv(FIXTURES / "fitzroy_kimberley_monthly.csv", parse_dates=["date"]).set_index("date")
    config = DynamicHydroYearConfig(expected_trough_month=11, trough_search_radius_months=3, max_invalid_pct=95.0)
    truth = _fitzroy_trough_truth()
    return monthly, config, truth


def _gilbert_inputs():
    monthly = pd.read_csv(FIXTURES / "gilbert_river_monthly.csv", parse_dates=["date"]).set_index("date")
    config = DynamicHydroYearConfig(expected_trough_month=9, trough_search_radius_months=3)
    truth = pd.read_csv(
        FIXTURES / "gilbert_river_reviewed_events.csv",
        parse_dates=["interval_start", "interval_end", "trough_month", "peak_month"],
    )
    detectable = truth["detectable"].astype(str).str.lower().eq("yes")
    truth = truth.loc[detectable].rename(columns={"trough_month": "truth_month"})
    truth = truth[["event_id", "interval_start", "interval_end", "truth_month"]]
    return monthly, config, truth


def _synthetic_inputs():
    panel = pd.read_csv(FIXTURES / "dynamic_state_mock.csv", parse_dates=["date"])
    monthly = panel.loc[panel["site"] == "intermittent"].set_index("date")[["extent_pct", "invalid_pct"]]
    config = DynamicHydroYearConfig(expected_trough_month=9, trough_search_radius_months=3)
    truth_frame = pd.read_csv(FIXTURES / "dynamic_state_truth.csv", parse_dates=["trough_month"])
    truth_frame = truth_frame.loc[
        (truth_frame["site"] == "intermittent") & (truth_frame["detectable"] == True)  # noqa: E712
    ].sort_values("trough_month").reset_index(drop=True)
    # Build the standard interval-scored truth format (same convention as the
    # Fitzroy/Gilbert fixtures): each event's window is (prior trough, this
    # trough], with the series start substituting for the first event's
    # missing prior trough.
    series_start = monthly.index.min()
    interval_start = [series_start] + list(truth_frame["trough_month"].iloc[:-1] + pd.DateOffset(months=1))
    truth = pd.DataFrame(
        {
            "event_id": truth_frame["hy_year"].astype(str),
            "interval_start": interval_start,
            "interval_end": truth_frame["trough_month"],
            "truth_month": truth_frame["trough_month"],
        }
    )
    return monthly, config, truth


_SITES = {
    "fitzroy": _fitzroy_inputs,
    "gilbert": _gilbert_inputs,
    "synthetic_intermittent": _synthetic_inputs,
}


def _run_detector(monthly: pd.DataFrame, config: DynamicHydroYearConfig, detector: str) -> pd.DataFrame:
    from dataclasses import replace

    return detect_dynamic_hydrological_years(monthly, config=replace(config, detector=detector))


def _aligned_with_support(actual: pd.DataFrame, truth: pd.DataFrame) -> pd.DataFrame:
    """Align truth events to actual trough months and join back selection_support."""
    trough_actual = actual.rename(columns={"trough_month": "actual_month"})[["actual_month"]]
    aligned = align_events_by_interval(truth, trough_actual)
    support_by_month = actual.set_index("trough_month")["selection_support"]
    support_by_month = support_by_month[support_by_month.index.notna()]
    aligned["selection_support"] = aligned["actual_month"].map(support_by_month)
    aligned["selection_support"] = aligned["selection_support"].fillna(0.0)
    return aligned


def _paired_abs_errors(aligned_robust: pd.DataFrame, aligned_semi: pd.DataFrame) -> pd.DataFrame:
    """Per-event paired absolute errors (months) for events both detectors resolved."""
    merged = aligned_robust[["event_id", "truth_month", "actual_month"]].merge(
        aligned_semi[["event_id", "truth_month", "actual_month"]],
        on=["event_id", "truth_month"],
        suffixes=("_robust", "_semi"),
    )
    resolved = merged["actual_month_robust"].notna() & merged["actual_month_semi"].notna()
    merged = merged.loc[resolved].copy()
    merged["abs_error_robust"] = (
        (merged["actual_month_robust"].dt.year - merged["truth_month"].dt.year) * 12
        + merged["actual_month_robust"].dt.month - merged["truth_month"].dt.month
    ).abs()
    merged["abs_error_semi"] = (
        (merged["actual_month_semi"].dt.year - merged["truth_month"].dt.year) * 12
        + merged["actual_month_semi"].dt.month - merged["truth_month"].dt.month
    ).abs()
    return merged[["abs_error_robust", "abs_error_semi"]]


def _site_block_bootstrap(per_site_pairs: dict[str, pd.DataFrame], n_resamples: int, seed: int) -> np.ndarray:
    """Site/year block bootstrap on mean(semi_abs_error - robust_abs_error).

    Each resample first draws which of the sites contribute (with replacement,
    weighted by their own event counts), then resamples that drawn site's own
    paired events with replacement -- this keeps a site's own within-site
    correlation intact rather than pooling all events as i.i.d. across sites.
    """
    rng = np.random.default_rng(seed)
    site_names = list(per_site_pairs.keys())
    site_arrays = {
        name: (frame["abs_error_semi"] - frame["abs_error_robust"]).to_numpy()
        for name, frame in per_site_pairs.items()
    }
    site_counts = np.array([len(site_arrays[name]) for name in site_names], dtype=float)
    site_weights = site_counts / site_counts.sum()

    results = np.empty(n_resamples)
    for i in range(n_resamples):
        drawn_sites = rng.choice(len(site_names), size=len(site_names), replace=True, p=site_weights)
        pooled = []
        for site_index in drawn_sites:
            name = site_names[site_index]
            values = site_arrays[name]
            resampled = rng.choice(values, size=len(values), replace=True)
            pooled.append(resampled)
        results[i] = np.concatenate(pooled).mean()
    return results


def _singleton_low_frame() -> pd.DataFrame:
    """The adversarial genuine-singleton-low fixture from test_boundary.py.

    A 7-month window with an isolated single-month low (September) that
    should NOT be excluded from trough candidacy by either detector.
    """
    index = pd.date_range("2020-06-01", periods=7, freq="MS")
    return pd.DataFrame({
        "extent_pct": [20, 15, 10, 1, 11, 16, 22],
        "invalid_pct": 0.0,
    }, index=index)


@pytest.mark.experimental
@pytest.mark.xfail(
    strict=False,
    reason="Experimental promotion-gate comparison harness; allowed to fail without blocking release.",
)
def test_semi_markov_promotion_gate():
    per_site_pairs: dict[str, pd.DataFrame] = {}
    pooled_aligned_robust = []
    pooled_aligned_semi = []

    robust_runtime_seconds = 0.0
    semi_runtime_seconds = 0.0

    for site_name, loader in _SITES.items():
        monthly, config, truth = loader()

        start = time.perf_counter()
        robust_actual = _run_detector(monthly, config, "robust_extrema")
        robust_runtime_seconds += time.perf_counter() - start

        start = time.perf_counter()
        semi_actual = _run_detector(monthly, config, "semi_markov")
        semi_runtime_seconds += time.perf_counter() - start

        aligned_robust = _aligned_with_support(robust_actual, truth)
        aligned_semi = _aligned_with_support(semi_actual, truth)

        per_site_pairs[site_name] = _paired_abs_errors(aligned_robust, aligned_semi)
        pooled_aligned_robust.append(aligned_robust)
        pooled_aligned_semi.append(aligned_semi)

    pooled_aligned_robust = pd.concat(pooled_aligned_robust, ignore_index=True)
    pooled_aligned_semi = pd.concat(pooled_aligned_semi, ignore_index=True)

    robust_metrics = summarize_timing(pooled_aligned_robust)
    semi_metrics = summarize_timing(pooled_aligned_semi)

    # Bootstrap CI on the paired difference (site/year block bootstrap).
    bootstrap_diffs = _site_block_bootstrap(per_site_pairs, _N_BOOTSTRAP, _BOOTSTRAP_SEED)
    semi_minus_robust_mae_ci_high = float(np.quantile(bootstrap_diffs, 0.975))

    # False singleton rejection (single 0/1 proxy, not a rate -- see brief).
    singleton_frame = prepare_monthly_extent(_singleton_low_frame())
    singleton_config = DynamicHydroYearConfig(expected_trough_month=9, trough_search_radius_months=3)
    robust_singleton = _find_robust_trough_opportunities(singleton_frame, singleton_config)
    semi_singleton = _find_semi_markov_trough_opportunities(singleton_frame, singleton_config)
    robust_false_singleton_rejection = int(
        pd.isna(robust_singleton.loc[robust_singleton["hy_year"] == 2020, "trough_month"].item())
    )
    semi_false_singleton_rejection = int(
        pd.isna(semi_singleton.loc[semi_singleton["hy_year"] == 2020, "trough_month"].item())
    )

    # Brier score: predicted prob of "resolved within 1 month" = selection_support
    # (0.0 when unresolved), outcome = 1 if abs_error <= 1 else 0 (unresolved -> 0).
    def _brier(aligned: pd.DataFrame) -> float:
        eligible = aligned["truth_month"].notna()
        rows = aligned.loc[eligible]
        resolved = rows["actual_month"].notna()
        abs_error = pd.Series(np.nan, index=rows.index, dtype=float)
        abs_error.loc[resolved] = (
            (rows.loc[resolved, "actual_month"].dt.year - rows.loc[resolved, "truth_month"].dt.year) * 12
            + rows.loc[resolved, "actual_month"].dt.month - rows.loc[resolved, "truth_month"].dt.month
        ).abs()
        outcome = ((abs_error <= 1) & resolved).astype(float)
        predicted = rows["selection_support"].astype(float)
        return float(((predicted - outcome) ** 2).mean())

    robust_brier = _brier(pooled_aligned_robust)
    semi_brier = _brier(pooled_aligned_semi)

    comparison = {
        "semi_minus_robust_mae_ci_high": semi_minus_robust_mae_ci_high,
        "semi_coverage": semi_metrics["coverage"],
        "robust_coverage": robust_metrics["coverage"],
        "semi_p90": semi_metrics["p90_abs_error_months"],
        "robust_p90": robust_metrics["p90_abs_error_months"],
        "semi_false_singleton_rejection": semi_false_singleton_rejection,
        "robust_false_singleton_rejection": robust_false_singleton_rejection,
        "semi_brier": semi_brier,
        "robust_brier": robust_brier,
        "semi_runtime_seconds": semi_runtime_seconds,
        "robust_runtime_seconds": robust_runtime_seconds,
    }
    print("Detector comparison:", comparison)

    assert comparison["semi_minus_robust_mae_ci_high"] < 0.0
    assert comparison["semi_coverage"] >= comparison["robust_coverage"] - 0.02
    assert comparison["semi_p90"] <= comparison["robust_p90"]
    assert comparison["semi_false_singleton_rejection"] <= comparison["robust_false_singleton_rejection"]
    assert comparison["semi_brier"] < comparison["robust_brier"]
    assert comparison["semi_runtime_seconds"] <= 5 * comparison["robust_runtime_seconds"]
