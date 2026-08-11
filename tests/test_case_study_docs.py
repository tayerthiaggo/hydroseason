from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

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


def test_daly_marginal_route_is_explained_by_both_regime_gates():
    main = Path("docs/case-studies/main-workflow.md").read_text(encoding="utf-8")
    overview = Path("docs/case-studies/index.md").read_text(encoding="utf-8")
    rainfall = Path("docs/case-studies/rainfall-context.md").read_text(
        encoding="utf-8"
    )
    summary = pd.read_csv("case_studies/results/main/summary.csv")
    rainfall_summary = pd.read_csv(
        "case_studies/results/main_rainfall/summary.csv"
    )
    daly = summary.loc[summary["key"] == "daly_river_nt"].iloc[0]
    daly_rain = rainfall_summary.loc[
        rainfall_summary["key"] == "daly_river_nt"
    ].iloc[0]

    assert daly["amplitude_snr"] == pytest.approx(2.459)
    assert daly["peak_phase_iqr_months"] == pytest.approx(2.0)
    assert daly_rain["peak_phase_iqr_months"] == pytest.approx(2.0)
    assert "seasonal minimum of 2.0" in main
    assert "seasonal maximum of 1.5 months" in main
    assert "Monsoonal tropical marginal" in overview
    assert "does not override its water regime" in rainfall
