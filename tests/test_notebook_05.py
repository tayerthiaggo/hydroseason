from __future__ import annotations

import json
from pathlib import Path


NOTEBOOK = Path("notebooks/05_0_1_improvements.ipynb")


def _source() -> str:
    payload = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    return "\n".join(
        "".join(cell.get("source", [])) for cell in payload["cells"]
    )


def test_notebook_05_is_public_api_only_and_hybrid():
    source = _source()
    compact = " ".join(source.split())
    assert "from hydroseason._" not in source
    assert "import hydroseason._" not in source
    assert "HYDROSEASON_RUN_LIVE_DEA" in source
    assert "HYDROSEASON_NOTEBOOK_OUTPUT" in source
    assert "run_hydroseason_many" in source
    assert "sys.executable" in source
    assert 'sys.executable, "-m", "hydroseason"' in compact


def test_notebook_05_does_not_fake_batch_outcomes():
    source = _source()
    assert "multi_aoi_contract" not in source
    assert "outcome position" not in source
    assert "batch.raise_for_failures()" in source


def test_notebook_index_lists_hybrid_release_routine():
    text = Path("notebooks/README.md").read_text(encoding="utf-8")
    assert "05_0_1_improvements.ipynb" in text
    assert "offline by default" in text
    assert "optional live DEA" in text
