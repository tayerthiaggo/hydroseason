from pathlib import Path


def test_decision_policy_document_contains_complete_promotion_gate():
    text = Path("docs/decision-policy.md").read_text(encoding="utf-8").casefold()
    required = (
        "new versioned decision-policy design",
        "predeclared metrics and acceptance thresholds",
        "synthetic calibration",
        "untouched synthetic validation partition",
        "independent real-catchment cohort",
        "empirical results or published scientific evidence",
        "comparison report",
        "migration notes",
        "regenerating expected fixtures",
    )
    assert all(phrase in text for phrase in required)
