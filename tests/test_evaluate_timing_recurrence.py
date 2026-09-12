import importlib.util
from pathlib import Path

import pandas as pd
import pytest

_SCRIPT = Path("scripts/evaluate_timing_recurrence.py")


def _module():
    spec = importlib.util.spec_from_file_location(
        "evaluate_timing_recurrence", _SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_wilson_upper_matches_known_values():
    module = _module()

    # At n=200 the acceptance boundary sits between 4 and 5 errors: 4 clears the
    # 0.05 bound, 5 does not. Pin both sides so a formula slip cannot pass.
    assert module.wilson_upper(0, 200) == pytest.approx(0.0133, rel=0.01)
    assert module.wilson_upper(4, 200) == pytest.approx(0.0438, rel=0.01)
    assert module.wilson_upper(4, 200) < module.FALSE_SEASONAL_BOUND
    assert module.wilson_upper(5, 200) > module.FALSE_SEASONAL_BOUND


def test_acceptance_fails_when_a_negative_family_exceeds_the_bound():
    module = _module()
    metrics = pd.DataFrame(
        [
            {
                "family": "white_noise",
                "truth_seasonal": False,
                "seasonal": 40,
                "n": 600,
            },
            {
                "family": "sinusoid",
                "truth_seasonal": True,
                "seasonal": 600,
                "n": 600,
                "n_years": 30,
            },
        ]
    )

    verdict = module.acceptance(metrics)

    assert verdict["false_seasonal"]["passed"] is False
    assert verdict["false_seasonal"]["failures"][0]["family"] == "white_noise"


def test_scoring_one_record_reports_both_policies():
    module = _module()
    from hydroseason._seasonality_synthetic import generate_seasonality_record

    record = generate_seasonality_record(family="sinusoid", n_years=7, replicate=0)
    row = module.score_record(record)

    assert row["family"] == "sinusoid"
    assert row["truth_seasonal"] is True
    assert row["established_regime"] in {
        "seasonal",
        "marginal",
        "aseasonal",
        "insufficient_record",
    }
    assert row["candidate_class"] in {"seasonal", "aseasonal", None}
    assert "candidate_peak_p" in row
