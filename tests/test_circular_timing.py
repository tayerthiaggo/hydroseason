import numpy as np
import pytest

from hydroseason._circular_timing import summarise_circular_months


def test_resultant_length_is_one_for_identical_january_values():
    summary = summarise_circular_months([1] * 12)

    assert summary.concentration == pytest.approx(1.0)
    assert summary.n == 12


def test_resultant_length_is_zero_for_one_observation_each_month():
    summary = summarise_circular_months(range(1, 13))

    assert summary.concentration == pytest.approx(0.0, abs=1e-15)


def test_circular_iqr_keeps_december_and_january_adjacent():
    summary = summarise_circular_months([12, 1, 12, 1])

    assert summary.iqr_months <= 2.0


def test_bootstrap_confidence_interval_is_deterministic():
    months = [12, 1, 1, 2, 12, 1, 2, 1]

    first = summarise_circular_months(months, n_resamples=40, random_state=7)
    second = summarise_circular_months(months, n_resamples=40, random_state=7)

    assert first == second
    assert first.ci_low is not None
    assert first.ci_high is not None


def test_kuiper_statistic_discriminates_concentrated_from_uniform_months():
    concentrated = summarise_circular_months([1, 1, 1, 2, 12, 1, 2, 1], n_resamples=40)
    uniform = summarise_circular_months(range(1, 13), n_resamples=40)

    assert concentrated.uniformity_p < 0.05
    assert uniform.uniformity_p > 0.05


def test_kuiper_null_calibration_matches_discrete_month_support():
    """The null distribution must be drawn from the same 12-point support as the data.

    Comparing a discrete-support observed statistic against a continuous U(0,1)
    null systematically inflates the observed statistic's apparent extremity,
    which biases p-values toward false rejection of uniformity (i.e. toward
    "seasonal" verdicts) even when months really are drawn uniformly at random.
    A well-calibrated test at alpha=0.1 should reject a truly uniform null in
    roughly 10% of trials, not far more.
    """
    rng = np.random.default_rng(12345)
    n_trials = 300
    n_per_trial = 36
    alpha = 0.1

    false_positives = 0
    for trial in range(n_trials):
        months = rng.integers(1, 13, size=n_per_trial)
        summary = summarise_circular_months(
            months, n_resamples=200, random_state=int(rng.integers(0, 1_000_000))
        )
        if summary.uniformity_p < alpha:
            false_positives += 1

    false_positive_rate = false_positives / n_trials
    assert false_positive_rate < 0.17, (
        f"empirical false-positive rate {false_positive_rate:.3f} at alpha={alpha} "
        "is far above nominal, indicating the null distribution's support does not "
        "match the discrete 12-month data support"
    )


@pytest.mark.parametrize(
    ("months", "error", "message"),
    [
        ([], ValueError, "months must not be empty"),
        ([1.5], ValueError, "months must contain integral values"),
        ([0], ValueError, "months must be integers from 1 to 12"),
        ([13], ValueError, "months must be integers from 1 to 12"),
        ([True], ValueError, "months must contain integral values"),
    ],
)
def test_invalid_months_raise_specific_errors(months, error, message):
    with pytest.raises(error, match=message):
        summarise_circular_months(months)


def test_invalid_resampling_configuration_raises_specific_errors():
    with pytest.raises(ValueError, match="n_resamples must be at least 20"):
        summarise_circular_months([1, 2, 3, 4], n_resamples=19)
    with pytest.raises(ValueError, match="confidence must be a number between 0 and 1"):
        summarise_circular_months([1, 2, 3, 4], confidence="0.95")
    with pytest.raises(ValueError, match="confidence must be between 0 and 1"):
        summarise_circular_months([1, 2, 3, 4], confidence=1.0)
    with pytest.raises(TypeError, match="random_state must be an integer"):
        summarise_circular_months([1, 2, 3, 4], random_state=1.5)


def test_public_function_accepts_numpy_integer_months():
    summary = summarise_circular_months(np.array([1, 2, 3, 4], dtype=np.int64))

    assert summary.n == 4
