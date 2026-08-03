import re

import numpy as np
import pandas as pd
import pytest

from hydroseason import CatchmentReportPaths, analyze_catchment, generate_catchment_report
from hydroseason.report import generate_html_report


@pytest.fixture
def seasonal_extent():
    dates = pd.date_range("2010-01-01", "2015-12-01", freq="MS")
    values = [
        max(0.0, min(100.0, 40.0 + 30.0 * np.sin(2 * np.pi * (date.month - 1) / 12)))
        for date in dates
    ]
    return pd.DataFrame({"extent_pct": values, "invalid_pct": 0.0}, index=dates)


@pytest.fixture
def aseasonal_extent():
    rng = np.random.default_rng(3)
    dates = pd.date_range("2010-01-01", periods=120, freq="MS")
    values = np.abs(rng.normal(0.15, 0.12, len(dates)))
    return pd.DataFrame({"extent_pct": values, "invalid_pct": 0.0}, index=dates)


def test_generate_catchment_report_writes_offline_bundle(tmp_path, seasonal_extent):
    paths = generate_catchment_report(
        seasonal_extent, tmp_path, name="Seasonal / test", title="Seasonal test"
    )
    html = paths.html.read_text(encoding="utf-8")

    assert isinstance(paths, CatchmentReportPaths)
    assert "Plotly.newPlot" in html
    assert "plotly-basic-3.6.0" in html
    assert "cdn.plot.ly" not in html
    assert "<script src=" not in html
    assert 'id="timeline-scale-linear"' in html
    assert 'id="timeline-scale-log"' in html
    assert 'id="timeline"' in html
    assert 'id="hydro-year"' in html
    assert html.count('class="plot plot-primary"') == 2
    assert html.index("Monthly Surface Water Extent") < html.index("Hydrological Year Extent")
    assert html.index("Hydrological Year Extent") < html.index("Supporting View")
    assert "plotly_relayout" in html
    assert "Invalid Coverage (%)" in html
    assert '"hydro_year"' in html
    assert 'data-theme="light"' in html
    assert "prefers-color-scheme" not in html
    assert paths.monthly_csv.exists()
    assert paths.hydro_years_csv.exists()
    assert paths.wet_event_csv.exists()
    assert paths.low_spells_csv.exists()
    assert not (tmp_path / "seasonal-test_summary.csv").exists()
    assert all(path.is_absolute() for path in paths.__dict__.values())
    assert paths.html.name == "seasonal-test.html"
    assert paths.monthly_csv.name == "seasonal-test_monthly.csv"

    monthly = pd.read_csv(paths.monthly_csv)
    hydro_years = pd.read_csv(paths.hydro_years_csv)
    events = pd.read_csv(paths.wet_event_csv)
    low_spells = pd.read_csv(paths.low_spells_csv)
    assert "condition_percentile" not in monthly.columns
    assert {
        "max_invalid_pct",
        "baseline_extent_pct",
        "is_hy_peak",
        "is_hy_mid_dry",
        "is_hy_trough",
        "phase_status",
        "quality_state",
    } <= set(monthly.columns)
    assert {"start_date", "peak_date", "trough_date"} <= set(hydro_years.columns)
    assert {"start_date", "end_date", "peak_date", "baseline_extent_pct"} <= set(events.columns)
    assert {"low_spell_id", "start_date", "end_date", "baseline_extent_pct"} <= set(low_spells.columns)


def test_generate_catchment_report_uses_default_name_for_blank_aoi(tmp_path, seasonal_extent):
    paths = generate_catchment_report(seasonal_extent, tmp_path, name="  ")

    assert paths.html.name == "hydroseason-results.html"
    assert paths.wet_event_csv.name == "hydroseason-results_wet_event.csv"
    assert not (tmp_path / "hydroseason-results_summary.csv").exists()
    assert "HydroSeason results" in paths.html.read_text(encoding="utf-8")


def test_generate_catchment_report_escapes_user_controlled_html(tmp_path, seasonal_extent):
    payload = '</script><script id="owned">window.owned=true</script><b>bad</b>'
    paths = generate_catchment_report(
        seasonal_extent,
        tmp_path,
        name=f"Catchment {payload}",
        title=f"Title {payload}",
        subtitle=f"Subtitle {payload}",
        quality_note=f"Quality {payload}",
    )
    html = paths.html.read_text(encoding="utf-8")

    assert '<script id="owned">' not in html
    assert "<b>bad</b>" not in html
    assert "&lt;b&gt;bad&lt;/b&gt;" in html
    assert re.search(r"<h1>.*&lt;script", html)


def test_generate_catchment_report_serializes_strict_json(tmp_path, seasonal_extent):
    extent = seasonal_extent.copy()
    extent.iloc[0, extent.columns.get_loc("extent_pct")] = np.nan

    paths = generate_catchment_report(extent, tmp_path, name="Strict JSON")
    html = paths.html.read_text(encoding="utf-8")
    app_payload = html.split("window.HydroSeasonReport = ", 1)[1].split(";</script>", 1)[0]

    assert "NaN" not in app_payload
    assert "Infinity" not in app_payload
    assert "<\\/" in html


def test_generate_catchment_report_rejects_inconsistent_supplied_analysis(
    tmp_path, seasonal_extent, aseasonal_extent
):
    analysis = analyze_catchment(aseasonal_extent, phase_model="rule_based", n_bootstrap=40)

    with pytest.raises(ValueError, match="analysis does not match"):
        generate_catchment_report(seasonal_extent, tmp_path, name="Mismatch", analysis=analysis)


def test_compatibility_report_uses_light_shell_without_csv_bundle(tmp_path, seasonal_extent):
    analysis = analyze_catchment(seasonal_extent, phase_model="rule_based", n_bootstrap=40)
    output = tmp_path / "legacy.html"

    result = generate_html_report(
        seasonal_extent,
        analysis.hydro_years.rename(columns={"hy_start": "start", "hy_end": "end"}),
        output,
        title="Legacy <b>title</b>",
        subtitle="Supplied years",
    )
    html = output.read_text(encoding="utf-8")

    assert result == output.resolve()
    assert "Plotly.newPlot" in html
    assert "cdn.plot.ly" not in html
    assert 'id="timeline"' in html
    assert 'id="hydro-year"' in html
    assert "&lt;b&gt;title&lt;/b&gt;" in html
    assert list(tmp_path.glob("*.csv")) == []


def test_aseasonal_bundle_has_no_hydrological_year_claims(tmp_path, aseasonal_extent):
    analysis = analyze_catchment(aseasonal_extent, phase_model="rule_based", n_bootstrap=40)
    paths = generate_catchment_report(aseasonal_extent, tmp_path, name="Dry test", analysis=analysis)
    html = paths.html.read_text(encoding="utf-8").casefold()
    hydro_years = pd.read_csv(paths.hydro_years_csv)

    assert hydro_years.empty
    assert "hydrological-year boundaries" not in html
    assert "wet events" in html
