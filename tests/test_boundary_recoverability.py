import numpy as np
import pandas as pd

from hydroseason._boundary import RobustBoundaryConfig
from hydroseason._boundary_recoverability import YearEvaluation, evaluate_year
from hydroseason._evidence import annual_extremum_month_sets
from hydroseason._state_input import prepare_monthly_extent

CONFIG = RobustBoundaryConfig()


def _seasonal_record(
    n_years=10, trough_month=7, amplitude=40.0, mean=50.0, jitter=None
):
    index = pd.date_range("2000-01-01", periods=12 * n_years, freq="MS")
    shift = (
        np.zeros(len(index))
        if jitter is None
        else np.repeat(jitter, 12)[: len(index)]
    )
    angle = 2.0 * np.pi * (np.asarray(index.month) - trough_month - shift) / 12.0
    values = np.clip(mean - (amplitude / 2.0) * np.cos(angle), 0.0, 100.0)
    return prepare_monthly_extent(
        pd.DataFrame(
            {"extent_pct": values, "invalid_pct": 0.0}, index=index
        )
    )


def _month_sets(prepared):
    return annual_extremum_month_sets(prepared, kind="min", tolerance_pct=1.0)


def test_stable_trough_is_recovered_with_zero_error():
    prepared = _seasonal_record()
    month_sets = _month_sets(prepared)

    evaluation = evaluate_year(
        prepared,
        year=2005,
        month_sets=month_sets,
        config=CONFIG,
        search_radius_months=3,
        min_usable_months=9,
    )

    assert isinstance(evaluation, YearEvaluation)
    assert evaluation.evaluable
    assert evaluation.resolved
    assert evaluation.error_months == 0.0
    assert evaluation.training_trough_month == 7


def test_training_phase_excludes_the_target_year():
    """The held-out year must not inform the phase it is scored against."""
    prepared = _seasonal_record()
    month_sets = dict(_month_sets(prepared))
    # Make 2005 wildly inconsistent; the training phase must be unmoved.
    month_sets[2005] = (1,)

    evaluation = evaluate_year(
        prepared,
        year=2005,
        month_sets=month_sets,
        config=CONFIG,
        search_radius_months=3,
        min_usable_months=9,
    )

    assert evaluation.training_trough_month == 7


def test_shifted_year_reports_nonzero_error():
    index = pd.date_range("2000-01-01", periods=12 * 10, freq="MS")
    angle = 2.0 * np.pi * (index.month - 7) / 12.0
    values = 50.0 - 20.0 * np.cos(angle)
    frame = pd.DataFrame({"extent_pct": values, "invalid_pct": 0.0}, index=index)
    # Push 2005's minimum four months late.
    mask = frame.index.year == 2005
    shifted = 50.0 - 20.0 * np.cos(
        2.0 * np.pi * (frame.index[mask].month - 11) / 12.0
    )
    frame.loc[mask, "extent_pct"] = shifted
    prepared = prepare_monthly_extent(frame)

    evaluation = evaluate_year(
        prepared,
        year=2005,
        month_sets=_month_sets(prepared),
        config=CONFIG,
        search_radius_months=3,
        min_usable_months=9,
    )

    assert evaluation.evaluable
    assert evaluation.error_months > 0.0


def test_sparse_year_is_not_evaluable():
    prepared = _seasonal_record()
    frame = prepared.copy()
    mask = frame.index.year == 2005
    keep = frame.index[mask][:4]
    frame.loc[mask, "extent_pct"] = np.nan
    frame.loc[keep, "extent_pct"] = 30.0
    prepared = prepare_monthly_extent(frame[["extent_pct", "invalid_pct"]])

    evaluation = evaluate_year(
        prepared,
        year=2005,
        month_sets=_month_sets(prepared),
        config=CONFIG,
        search_radius_months=3,
        min_usable_months=9,
    )

    assert not evaluation.evaluable
    assert "usable months" in evaluation.reason


def test_error_is_zero_anywhere_inside_the_equivalent_low_run():
    """A flat trough must not be penalised for the detector picking either end."""
    index = pd.date_range("2000-01-01", periods=12 * 10, freq="MS")
    values = np.tile(np.array([60.0] * 5 + [10.0, 10.0, 10.0] + [60.0] * 4), 10)
    prepared = prepare_monthly_extent(
        pd.DataFrame({"extent_pct": values, "invalid_pct": 0.0}, index=index)
    )

    evaluation = evaluate_year(
        prepared,
        year=2005,
        month_sets=_month_sets(prepared),
        config=CONFIG,
        search_radius_months=3,
        min_usable_months=9,
    )

    assert evaluation.error_months == 0.0


def test_error_across_the_december_january_boundary_is_circular():
    prepared = _seasonal_record(trough_month=1)

    evaluation = evaluate_year(
        prepared,
        year=2005,
        month_sets=_month_sets(prepared),
        config=CONFIG,
        search_radius_months=3,
        min_usable_months=9,
    )

    assert evaluation.evaluable
    assert evaluation.error_months == 0.0


def test_single_year_record_cannot_be_evaluated():
    prepared = _seasonal_record(n_years=1)

    evaluation = evaluate_year(
        prepared,
        year=2000,
        month_sets=_month_sets(prepared),
        config=CONFIG,
        search_radius_months=3,
        min_usable_months=9,
    )

    assert not evaluation.evaluable
    assert "training" in evaluation.reason


def test_held_out_trough_outside_candidate_window_has_nonzero_error():
    """A held-out trough outside the configured candidate window has non-zero error even though it is the full-interval reference minimum."""
    index = pd.date_range("2000-01-01", periods=12 * 10, freq="MS")
    angle = 2.0 * np.pi * (np.asarray(index.month) - 7) / 12.0
    values = np.clip(50.0 - 20.0 * np.cos(angle), 0.0, 100.0)
    frame = pd.DataFrame({"extent_pct": values, "invalid_pct": 0.0}, index=index)
    # In 2005, make month 12 the true minimum in the 12-month reference window
    mask = frame.index.year == 2005
    shifted = np.clip(
        50.0
        - 20.0
        * np.cos(2.0 * np.pi * (np.asarray(frame.index[mask].month) - 12) / 12.0),
        0.0,
        100.0,
    )
    frame.loc[mask, "extent_pct"] = shifted
    prepared = prepare_monthly_extent(frame)

    evaluation = evaluate_year(
        prepared,
        year=2005,
        month_sets=_month_sets(prepared),
        config=CONFIG,
        search_radius_months=2,
        min_usable_months=9,
    )
    assert evaluation.evaluable
    assert evaluation.error_months is not None and evaluation.error_months >= 3.0


def test_two_disjoint_low_episodes_do_not_become_one_equivalent_low_run():
    """Two disjoint low episodes do not become one contiguous run."""
    from hydroseason._boundary import select_window_minimum

    index = pd.date_range("2000-01-01", periods=12, freq="MS")
    vals = np.array(
        [50.0, 5.0, 50.0, 50.0, 50.0, 50.0, 50.0, 50.0, 50.0, 5.0, 50.0, 50.0]
    )
    prepared = prepare_monthly_extent(
        pd.DataFrame({"extent_pct": vals, "invalid_pct": 0.0}, index=index)
    )
    expected = pd.Timestamp("2000-02-01")
    sel = select_window_minimum(
        prepared,
        expected=expected,
        expected_count=12,
        noise_pp=1.0,
        amplitude_pp=45.0,
        config=CONFIG,
    )
    assert sel.run_start == pd.Timestamp("2000-02-01")
    assert sel.run_end == pd.Timestamp("2000-02-01")
