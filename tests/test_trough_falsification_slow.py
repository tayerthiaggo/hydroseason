"""Pre-registered known-truth checks of the circular Kuiper timing tests.

Bounds are binomial sampling-error bounds at the method's own alpha of 0.05 and
were fixed before the first run. They are not method thresholds. A failing test is a finding to record in
docs/provisional-trough-falsification-2026-10-30.md, never a reason to change
library code or to loosen the bound.

Runtime is roughly two minutes; run with ``-m slow``.
"""

import pytest

from hydroseason import assess_water_regime
from hydroseason._seasonality_test import TIMING_RECURRENCE_ALPHA
from scripts.trough_synthetic import build_record

pytestmark = pytest.mark.slow


def _rejections(kind, *, seeds, flood_rate, which):
    """Count seeds whose ``which`` ("peak" or "trough") test rejects uniformity."""
    count = 0
    for seed in range(seeds):
        _, frame = build_record(kind, seed=seed, flood_rate=flood_rate)
        test = assess_water_regime(frame, n_bootstrap=50).seasonality_test
        summary = getattr(test, which)
        p_value = summary.uniformity_p
        count += p_value is not None and p_value < TIMING_RECURRENCE_ALPHA
    return count


def test_trough_test_false_positive_rate_on_drifting_trough_with_floods():
    rejections = _rejections("drift", seeds=100, flood_rate=0.3, which="trough")

    assert rejections <= 10, f"trough rejections under drift: {rejections}/100"


def test_trough_test_power_on_recurrent_trough_with_floods():
    rejections = _rejections("stable", seeds=100, flood_rate=0.3, which="trough")

    assert rejections >= 90, f"trough rejections on recurrent trough: {rejections}/100"


def test_trough_test_holds_alpha_under_a_uniform_null():
    rejections = _rejections("uniform", seeds=200, flood_rate=0.0, which="trough")

    assert rejections <= 17, f"trough rejections under uniform null: {rejections}/200"


def test_peak_test_holds_alpha_under_a_uniform_null():
    rejections = _rejections("uniform", seeds=200, flood_rate=0.0, which="peak")

    assert rejections <= 17, f"peak rejections under uniform null: {rejections}/200"
