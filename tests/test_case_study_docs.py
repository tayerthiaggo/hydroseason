from __future__ import annotations

from pathlib import Path

from scripts.render_case_study_docs import render_case_study_docs


def test_rendered_case_study_tables_match_checked_results():
    assert render_case_study_docs(Path.cwd(), check=True) == 0


def test_readme_release_copy_has_no_stale_markers():
    text = Path("README.md").read_text(encoding="utf-8")
    assert "Until the first PyPI release" not in text
    assert "XXXXXXX" not in text
    assert 'pip install "hydroseason[stac]"' in text
    assert "hydroseason==0.1.1" not in text


def test_api_docs_name_all_dea_cache_entry_points():
    text = Path("docs/api/io.md").read_text(encoding="utf-8")
    for name in (
        "open_wo_statistics",
        "open_completed_mask_cache",
        "verify_cache_footprints",
        "open_completed_dual_extent_counts",
    ):
        assert name in text
