import numpy as np
import pytest

from hydroseason._evidence import wilson_interval


def test_four_of_five_has_a_low_lower_bound():
    """The number that motivates the gate: 80% of five is weak evidence."""
    low, high = wilson_interval(4, 5)

    assert low == pytest.approx(0.376, abs=0.01)
    assert high == pytest.approx(0.964, abs=0.01)


def test_five_of_five_is_stronger_than_four_of_five():
    low_perfect, _ = wilson_interval(5, 5)
    low_partial, _ = wilson_interval(4, 5)

    assert low_perfect > low_partial
    assert low_perfect == pytest.approx(0.566, abs=0.01)


def test_more_trials_narrow_the_interval_at_the_same_rate():
    low_small, high_small = wilson_interval(8, 10)
    low_large, high_large = wilson_interval(80, 100)

    assert (high_large - low_large) < (high_small - low_small)
    assert low_large > low_small


def test_bounds_stay_inside_zero_and_one():
    for successes, trials in [(0, 1), (1, 1), (0, 50), (50, 50)]:
        low, high = wilson_interval(successes, trials)
        assert 0.0 <= low <= high <= 1.0


def test_zero_trials_returns_the_widest_interval():
    assert wilson_interval(0, 0) == (0.0, 1.0)


def test_successes_cannot_exceed_trials():
    with pytest.raises(ValueError, match="successes"):
        wilson_interval(6, 5)


def test_interval_is_finite_for_every_rate():
    for successes in range(0, 21):
        low, high = wilson_interval(successes, 20)
        assert np.isfinite(low) and np.isfinite(high)
