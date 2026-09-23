from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]




def test_docs_name_the_only_method_and_manifest():
    combined = "\n".join(
        (Path(path) if Path(path).is_file() else ROOT / path).read_text(encoding="utf-8")
        for path in ("README.md", "docs/methods.md", "docs/cli-recipes.md")
    )
    assert "hydroseason-v0.2.0" in combined
    assert "run manifest" in combined.lower()
    assert "--method-policy" not in combined
    assert "candidate_timing_recurrence" not in combined
    assert "established_0_2_0" not in combined


def test_library_docs_do_not_claim_completed_evidence_absent_from_receipts():
    methods_path = Path("docs/methods.md") if Path("docs/methods.md").is_file() else ROOT / "docs/methods.md"
    receipts_path = Path("docs/evidence-receipts.json") if Path("docs/evidence-receipts.json").is_file() else ROOT / "docs/evidence-receipts.json"
    methods = methods_path.read_text(encoding="utf-8")
    receipts = json.loads(receipts_path.read_text(encoding="utf-8"))
    for item in receipts["evidence"]:
        assert item["stage"] in methods
        assert str(item["denominator"]) in methods


