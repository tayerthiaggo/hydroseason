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
    with pytest.raises(ValueError, match="confidence must be between 0 and 1"):
        summarise_circular_months([1, 2, 3, 4], confidence=1.0)
    with pytest.raises(TypeError, match="random_state must be an integer"):
        summarise_circular_months([1, 2, 3, 4], random_state=1.5)


def test_public_function_accepts_numpy_integer_months():
    summary = summarise_circular_months(np.array([1, 2, 3, 4], dtype=np.int64))

    assert summary.n == 4
