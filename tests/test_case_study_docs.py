from __future__ import annotations

import re
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


def test_release_docs_explain_batch_seasonality_and_map_contracts():
    """Removing a released 0.1.1 user contract must fail documentation checks."""
    readme = Path("README.md").read_text(encoding="utf-8")
    guide = Path("docs/guide.md").read_text(encoding="utf-8")
    workflow = Path("docs/api/workflow.md").read_text(encoding="utf-8")
    analysis = Path("docs/api/analysis.md").read_text(encoding="utf-8")
    report = Path("docs/api/report.md").read_text(encoding="utf-8")
    columns = Path("docs/report-columns.md").read_text(encoding="utf-8")
    citations = Path("docs/citation.md").read_text(encoding="utf-8")
    all_docs = "\n".join((readme, guide, workflow, analysis, report, columns, citations))

    sample = '''run_hydroseason_many(
    "catchments.gpkg",
    output_dir="results",
    cache_dir="cache",
    start_date="2000-01-01",
    end_date="2025-12-01",
    id_col="catchment_id",
    workers="auto",
)'''
    assert sample in guide
    assert "for outcome in batch.outcomes:" in guide
    assert "batch.raise_for_failures()" in guide

    for phrase in (
        "run_hydroseason_many",
        "one input row produces one analysis and one report",
        'workers="auto"',
        "60% of currently available RAM",
        "default concurrency cap of 2",
        "30 usable annual timings",
        "not 30 months",
        "mean resultant length",
        "Kuiper",
        "OpenStreetMap",
        "internet connection",
        "theta_y = 2*pi*(m_y - 1)/12",
        "R = |mean(exp(i*theta_y))|",
        "10.1029/2019JD031381",
        "10.5194/hess-22-3883-2018",
        "10.1029/2003WR002295",
        "10.1002/hyp.11365",
        "10.1016/j.advwatres.2015.11.009",
    ):
        assert phrase in all_docs

    assert "SNR > 1.5" not in guide
    assert "SNR ≤ 1.5" not in guide
    assert "1.5 months" not in guide
