import json
import re
import shutil
import subprocess
import textwrap

import numpy as np
import pandas as pd
import pytest

from hydroseason import CatchmentReportPaths, analyze_catchment, generate_catchment_report
from hydroseason._aoi_context import AOIContext
from hydroseason._regime_compare import compare_rainfall_to_extent_regime
from hydroseason._report_html import render_report_html
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
    assert '<div id="timeline" class="plot-canvas"></div>' in html
    assert '<div id="secondary" class="plot-canvas"></div>' in html
    assert html.count('class="kpi"') == 18
    assert html.index("hydrological years") < html.index("mean annual amplitude")
    assert html.index("peak timing concentration") < html.index("trough timing concentration")
    assert html.index("trough timing concentration") < html.index("analytical route")
    assert html.index("average invalid/cloud cover") > html.index("high confidence years")
    assert ".plot > .plot-canvas {" in html
    assert ".plot-primary > .plot-canvas {" in html
    assert ".plot > div {" not in html
    assert ".plot-primary > div {" not in html
    assert html.count('class="plot plot-primary"') == 1
    assert "Hydrological Year Extent" not in html
    assert html.index("Monthly Surface Water Extent") < html.index("Seasonal Context")
    assert "function synchronize(" not in html
    assert "Invalid Coverage (%)" not in html
    assert '"hydro_year"' not in html
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


def test_report_interactions_restore_scale_without_secondary_range_sync(tmp_path):
    """Execute emitted scale and phase interactions against a minimal Plotly DOM."""
    node = shutil.which("node")
    assert node is not None, "Node.js 20+ is required for the report interaction test"
    version = subprocess.run([node, "--version"], capture_output=True, text=True, check=False)
    assert version.returncode == 0, version.stderr
    assert int(version.stdout.strip().removeprefix("v").split(".", 1)[0]) >= 20
    timeline = {
        "data": [
            {"name": "Reference Median", "x": ["2020-01-01", "2020-02-01"], "y": [-1, 2], "customdata": [-1, 2], "hovertemplate": "Reference Median: %{customdata}%", "meta": {"original_y": [-1, 2], "log_floor": 0.02, "log_safe_y": [0.02, 2]}},
            {"name": "Extent", "x": ["2020-01-01", "2020-02-01"], "y": [0, 4], "customdata": [[0, -1, 7, "dry", 2020, "HY End Dry"], [4, 2, 0, "recovery", 2021, "None"]], "meta": {"original_y": [0, 4], "log_floor": 0.02, "log_safe_y": [0.02, 4]}},
            {"name": "Invalid", "x": ["2020-01-01"], "y": [7], "yaxis": "y2"},
        ],
        "layout": {"xaxis": {"range": ["2019-01-01", "2019-12-01"]}, "yaxis": {"type": "linear"}, "yaxis2": {"type": "linear"}},
        "config": {"responsive": True},
    }
    html = render_report_html(
        name="Test",
        title="Test",
        subtitle=None,
        quality_note=None,
        verdict="Test verdict",
        kpis=[],
        monthly=pd.DataFrame(),
        hydro_years=pd.DataFrame(),
        events=pd.DataFrame(),
        low_spells=pd.DataFrame(),
        summary=pd.DataFrame(),
        timeline_figure=timeline,
        secondary_figure={"data": [], "layout": {}, "config": {"responsive": True}},
    )
    interaction = re.findall(r"<script>\s*(\(\(\) => .*?)</script>", html, flags=re.DOTALL)[-1]
    script = tmp_path / "report-interactions.js"
    script.write_text(
        textwrap.dedent(
            f"""
            const assert = require("node:assert/strict");
            const vm = require("node:vm");
            const clone = value => structuredClone(value);
            class Element {{
              constructor(id) {{ this.id = id; this.listeners = {{}}; this.attrs = {{}}; this.classList = {{ active: false, toggle: (name, on) => this.classList[name] = on }}; }}
              on(name, fn) {{ this.listeners[name] = fn; }}
              emit(name, event) {{ this.listeners[name](event); }}
              addEventListener(name, fn) {{ this.listeners[name] = fn; }}
              setAttribute(name, value) {{ this.attrs[name] = value; }}
            }}
            const elements = Object.fromEntries(["timeline", "secondary", "timeline-scale-linear", "timeline-scale-log"].map(id => [id, new Element(id)]));
            const Plotly = {{
              newPlot(target, data, layout) {{ target.data = clone(data); target.layout = clone(layout); return Promise.resolve(target); }},
              restyle(target, update, indices) {{ indices.forEach((index, position) => target.data[index].y = clone(update.y[position])); return Promise.resolve(target); }},
                relayout(target, update) {{
                    if (update["yaxis.type"]) target.layout.yaxis.type = update["yaxis.type"];
                    return Promise.resolve(target);
                }},
            }};
            const context = {{ window: {{ HydroSeasonReport: {html.split('window.HydroSeasonReport = ', 1)[1].split(';</script>', 1)[0]} }}, document: {{ getElementById: id => elements[id] }}, Plotly, Promise, Array, Number, String }};
            vm.runInNewContext({interaction!r}, context);
            (async () => {{
              await Promise.resolve(); await Promise.resolve();
              elements["timeline-scale-log"].listeners.click();
              assert.deepEqual(elements.timeline.data[0].y, [0.02, 2]);
              assert.deepEqual(elements.timeline.data[0].customdata, [-1, 2]);
              assert.equal(elements.timeline.data[0].hovertemplate, "Reference Median: %{{customdata}}%");
              elements["timeline-scale-linear"].listeners.click();
              assert.deepEqual(elements.timeline.data[0].y, [-1, 2]);
              assert.deepEqual(elements.timeline.data[1].y, [0, 4]);
              assert.equal(elements.timeline.layout.yaxis2.type, "linear");
              assert.equal(elements.timeline.listeners.plotly_relayout, undefined);
            }})().catch(error => {{ console.error(error); process.exitCode = 1; }});
            """
        ),
        encoding="utf-8",
    )
    result = subprocess.run([node, str(script)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


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


def test_generate_catchment_report_embeds_a_safe_aoi_map(tmp_path, seasonal_extent):
    """Removing map rendering or escaping would lose the map or permit script injection."""
    payload = '</script><script id="owned">window.owned=true</script>'
    context = AOIContext(
        geojson=json.dumps(
            {
                "type": "FeatureCollection",
                "features": [],
                "properties": {"payload": payload},
            }
        ),
        bounds_wgs84=(115.0, -32.0, 116.0, -31.0),
        display_name=f"AOI {payload}",
        feature_count=0,
    )

    paths = generate_catchment_report(
        seasonal_extent, tmp_path, aoi_context=context
    )
    html = paths.html.read_text(encoding="utf-8")

    assert '<section id="aoi-context">' in html
    assert 'id="aoi-map-report"' in html
    assert "tile.openstreetmap.org" in html
    assert "data:image/png;base64" not in html
    assert "&lt;/script&gt;" in html
    assert "<\\/script>" in html
    assert payload not in html


def test_generate_catchment_report_warns_and_continues_when_map_rendering_fails(
    monkeypatch, tmp_path, seasonal_extent
):
    """A report-map rendering failure is presentation-only, never fatal."""
    context = AOIContext("{}", (115.0, -32.0, 116.0, -31.0), "AOI", 0)

    def fail_map(*args, **kwargs):
        raise RuntimeError("map assets unavailable")

    monkeypatch.setattr("hydroseason.report.render_aoi_map_html", fail_map)
    with pytest.warns(UserWarning, match="map assets unavailable"):
        paths = generate_catchment_report(
            seasonal_extent, tmp_path, aoi_context=context
        )

    assert paths.html.exists()
    assert 'id="aoi-context"' not in paths.html.read_text(encoding="utf-8")


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
    assert 'id="hydro-year"' not in html
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


def test_report_renders_event_and_low_spell_panels_with_grounded_explainers(
    tmp_path, aseasonal_extent
):
    """The event/low-spell charts and their above-the-graph prose both appear,
    and the prose states this record's own resolved threshold numbers rather
    than generic boilerplate."""
    analysis = analyze_catchment(aseasonal_extent, phase_model="rule_based", n_bootstrap=40)
    assert analysis.events.summary["n_events"] > 0
    assert analysis.events.summary["n_low_spells"] > 0

    paths = generate_catchment_report(
        aseasonal_extent, tmp_path, name="Event test", analysis=analysis
    )
    html = paths.html.read_text(encoding="utf-8")
    app_payload = html.split("window.HydroSeasonReport = ", 1)[1].split(";</script>", 1)[0]
    report_data = json.loads(app_payload)

    assert "Wet Event Characterisation" in html
    assert "Low-Extent Spells" in html
    assert 'id="events"' in html
    assert 'id="low-spells"' in html
    assert "events" in report_data["figures"]
    assert "low_spells" in report_data["figures"]

    enter_pct = round(analysis.events.summary["enter_threshold_pct"], 1)
    low_pct = round(analysis.events.summary["low_threshold_pct"], 1)
    assert f"{enter_pct}" in html
    assert f"{low_pct}" in html
    assert "hysteresis" in html
    assert "independently of wet events" in html
    # The old static, catchment-agnostic caption must be gone.
    assert "Duration of each wet event, in order of occurrence." not in html


def test_report_adds_collapsible_rainfall_context(
    tmp_path, seasonal_extent
):
    analysis = analyze_catchment(
        seasonal_extent, phase_model="rule_based", n_bootstrap=40
    )
    rainfall = pd.DataFrame(
        {"rainfall_mm": np.linspace(1, 120, len(seasonal_extent))},
        index=seasonal_extent.index,
    )
    comparison = compare_rainfall_to_extent_regime(analysis.regime, rainfall)
    paths = generate_catchment_report(
        seasonal_extent,
        tmp_path,
        analysis=analysis,
        rainfall=rainfall,
        rainfall_comparison=comparison,
        rainfall_source="silo",
    )
    html = paths.html.read_text(encoding="utf-8")
    app_payload = html.split("window.HydroSeasonReport = ", 1)[1].split(
        ";</script>", 1
    )[0]
    report_data = json.loads(app_payload)

    assert '<details class="rainfall-context">' in html
    assert "Rainfall context (SILO)" in html
    assert "Rainfall regime" in html
    assert "Extent SNR" in html
    assert "Rain SNR" in html
    assert "Peak lag" in html
    assert 'id="rainfall-context-figure"' in html
    rainfall_trace = next(
        trace
        for trace in report_data["figures"]["timeline"]["data"]
        if trace.get("name") == "Rainfall"
    )
    assert rainfall_trace["yaxis"] == "y2"


def test_report_omits_rainfall_context_when_absent(tmp_path, seasonal_extent):
    paths = generate_catchment_report(seasonal_extent, tmp_path)
    html = paths.html.read_text(encoding="utf-8")
    assert "Rainfall context (" not in html
    assert 'id="rainfall-context-figure"' not in html


def test_report_keeps_rainfall_when_comparison_failed(tmp_path, seasonal_extent):
    rainfall = pd.DataFrame(
        {"rainfall_mm": np.linspace(1, 120, len(seasonal_extent))},
        index=seasonal_extent.index,
    )
    paths = generate_catchment_report(
        seasonal_extent,
        tmp_path,
        rainfall=rainfall,
        rainfall_source="csv",
        rainfall_comparison_warning="comparison unavailable",
    )
    html = paths.html.read_text(encoding="utf-8")
    assert "Rainfall context (supplied CSV)" in html
    assert "comparison unavailable" in html
    assert "Mean Monthly Rainfall" in html


def test_report_escapes_rainfall_warning(tmp_path, seasonal_extent):
    payload = '</script><script id="rain-owned">window.owned=true</script>'
    paths = generate_catchment_report(
        seasonal_extent,
        tmp_path,
        rainfall_warning=payload,
    )
    html = paths.html.read_text(encoding="utf-8")

    assert '<script id="rain-owned">' not in html
    assert "&lt;/script&gt;" in html
