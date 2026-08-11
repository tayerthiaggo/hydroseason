from __future__ import annotations

from pathlib import Path
import re

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


def test_case_study_reports_surface_circular_timing_and_daly_trough_route():
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
    daly_rain = rainfall_summary.loc[rainfall_summary["key"] == "daly_river_nt"].iloc[0]

    assert daly["amplitude_snr"] == pytest.approx(2.459)
    assert daly["regime"] == daly_rain["regime"] == "seasonal"
    assert daly["route"] == daly_rain["route"] == "per_year_detection"
    assert "trough timing CI lower bound" in daly["route_reason"]
    assert "trough timing CI lower bound" in daly_rain["route_reason"]
    assert "trough timing concentration" in main
    assert "1.5 months" not in main
    assert "Monsoonal tropical seasonal" in overview
    assert "rainfall is ancillary by design" in rainfall


def test_regenerated_case_study_reports_have_timing_summaries_without_aoi_maps():
    report_dirs = (
        Path("case_studies/results/main"),
        Path("case_studies/results/main_rainfall"),
    )
    reports = [report for directory in report_dirs for report in directory.glob("*/*.html")]

    assert len(reports) == 10
    for report in reports:
        text = report.read_text(encoding="utf-8")
        assert "peak timing concentration" in text
        assert "trough timing concentration" in text
        assert "95% bootstrap CI" in text
        assert "IQR is descriptive only" in text
        assert re.search(
            r"Kuiper uniformity p-value\s+0\.\d{3}", text
        ), report
        assert "n_timing_years=21" in text
        assert "Only 21 annual timing observations are available; fewer than 30" in text
        assert '<section id="aoi-context">' not in text
