"""Tests for scripts/build_multi_catchment_html.py's resolution-stamp rendering.

These exercise HTML-generation helpers (``_characterization_card``,
``_comparison_figure``, ``build_report``) with synthetic ``result`` dicts and
assert on substrings of the rendered HTML output -- no real STAC/raster data,
no real checkpoints. The module under test lives outside the ``hydroseason``
package (it's a standalone script in ``scripts/``), so it is loaded directly
from its file path via ``importlib``, matching the pattern used in
``tests/test_run_multi_catchment_report.py`` for its sibling script.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "build_multi_catchment_html.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "build_multi_catchment_html_under_test", SCRIPT_PATH
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def mod():
    m = _load_module()
    yield m
    sys.modules.pop(m.__name__, None)


class _FakeSpec:
    def __init__(self, key="test_catchment", display_name="Test Catchment"):
        self.key = key
        self.display_name = display_name
        self.river = "Test River"
        self.region = "Test Region"
        self.regime_note = "Some regime note."


class _FakePattern:
    def __init__(self, pattern="unimodal_annual", seasonal_strength=0.7, bootstrap_support=0.9):
        self.pattern = pattern
        self.seasonal_strength = seasonal_strength
        self.bootstrap_support = bootstrap_support


def _fake_hydro_years():
    return pd.DataFrame({
        "status": ["complete", "complete"],
        "hy_year": [2020, 2021],
        "hy_start": pd.to_datetime(["2020-07-01", "2021-07-01"]),
        "hy_end": pd.to_datetime(["2021-06-30", "2022-06-30"]),
        "peak_month": pd.to_datetime(["2021-02-01", "2022-02-01"]),
        "trough_month": pd.to_datetime(["2020-10-01", "2021-10-01"]),
        "peak_extent_pct": [60.0, 65.0],
        "trough_extent_pct": [10.0, 12.0],
        "annual_condition": ["typical_or_mixed", "high"],
    })


def _fake_extent():
    idx = pd.date_range("2020-07-01", periods=6, freq="MS")
    return pd.DataFrame({
        "extent_pct": [10.0, 20.0, 60.0, 55.0, 30.0, 12.0],
        "invalid_pct": [1.0] * 6,
        "n_valid": [100] * 6,
    }, index=idx)


def _fake_geo():
    return {"area_km2": 1234.0, "n_stream_reaches": 10, "bounds_wgs84": [140.0, -20.0, 140.5, -19.5]}


def _fake_result(**overrides):
    result = {
        "spec": _FakeSpec(),
        "geo": _fake_geo(),
        "pattern": _FakePattern(),
        "hydro_years": _fake_hydro_years(),
        "extent": _fake_extent(),
        "resolution_m": 30.0,
        "n_valid": 100,
        "projected_noise_floor_pp": 0.75,
        "reason": "ok",
        "guard_caveat": None,
        "pattern_claim_excluded": False,
    }
    result.update(overrides)
    return result


class TestResolutionKpisInCard:
    def test_card_shows_resolution_n_valid_and_noise_floor(self, mod):
        result = _fake_result(resolution_m=25.0, n_valid=456, projected_noise_floor_pp=1.23)
        card = mod._characterization_card(result)

        assert "25 m" in card
        assert "456" in card
        assert "1.23 pp" in card


class TestGuardCaveatRendering:
    def test_caveat_present_renders_labelled_block(self, mod):
        result = _fake_result(guard_caveat="Thin-channel guard: coarsening refused past 100m.")
        card = mod._characterization_card(result)

        assert "caveat" in card.lower()
        assert "Thin-channel guard: coarsening refused past 100m." in card

    def test_caveat_none_renders_no_caveat_block(self, mod):
        result = _fake_result(guard_caveat=None)
        card = mod._characterization_card(result)

        assert "caveat-block" not in card

    def test_caveat_text_is_html_escaped(self, mod):
        malicious = "<script>alert('xss')</script> & <b>bold</b>"
        result = _fake_result(guard_caveat=malicious)
        card = mod._characterization_card(result)

        assert "<script>alert" not in card
        assert "&lt;script&gt;" in card


class TestPatternClaimExcludedFraming:
    def test_excluded_true_shows_resolution_flagged_framing(self, mod):
        result = _fake_result(pattern_claim_excluded=True)
        card = mod._characterization_card(result)

        assert "resolution-flagged" in card.lower()
        assert "shape" in card.lower()

    def test_excluded_false_shows_no_flagged_framing(self, mod):
        result = _fake_result(pattern_claim_excluded=False)
        card = mod._characterization_card(result)

        assert "resolution-flagged" not in card.lower()


class TestStressTrustChips:
    def test_card_shows_qualified_condition_and_timing_confidence_chips(self, mod):
        hy = _fake_hydro_years()
        hy["annual_condition_qualified"] = ["typical_uncertain", "high"]
        hy["timing_confidence"] = ["low", "high"]
        result = _fake_result(hydro_years=hy)

        card = mod._characterization_card(result)

        assert "typical uncertain: 1" in card
        assert "high: 1" in card
        assert "low: 1" in card

    def test_card_handles_missing_stress_trust_columns_without_crash(self, mod):
        result = _fake_result()  # _fake_hydro_years() has no qualified/timing_confidence cols

        card = mod._characterization_card(result)

        assert "catchment-section" in card

    def test_stress_trust_chip_values_are_html_escaped(self, mod):
        hy = _fake_hydro_years()
        hy["annual_condition_qualified"] = ["<script>evil</script>", "high"]
        hy["timing_confidence"] = ["low", "high"]
        result = _fake_result(hydro_years=hy)

        card = mod._characterization_card(result)

        assert "<script>evil" not in card
        assert "&lt;script&gt;" in card


class TestBackwardCompatibility:
    def test_card_handles_missing_new_keys_without_crash(self, mod):
        result = _fake_result()
        for key in (
            "resolution_m", "n_valid", "projected_noise_floor_pp",
            "reason", "guard_caveat", "pattern_claim_excluded",
        ):
            result.pop(key, None)

        # Must not raise -- pre-Task-6 checkpoints lack these keys entirely.
        card = mod._characterization_card(result)
        assert "catchment-section" in card

    def test_build_report_handles_missing_new_keys_without_crash(self, mod, tmp_path):
        result = _fake_result()
        for key in (
            "resolution_m", "n_valid", "projected_noise_floor_pp",
            "reason", "guard_caveat", "pattern_claim_excluded",
        ):
            result.pop(key, None)

        out_path = tmp_path / "report.html"
        written = mod.build_report([result], out_path)
        assert written.exists()


class TestComparisonAndSummaryResolutionStamp:
    def test_summary_table_shows_resolution_column(self, mod, tmp_path):
        result = _fake_result(resolution_m=50.0)
        out_path = tmp_path / "report.html"
        mod.build_report([result], out_path)
        doc = out_path.read_text(encoding="utf-8")

        assert "Resolution" in doc
        assert "50 m" in doc

    def test_comparison_figure_includes_resolution_in_label(self, mod):
        result = _fake_result(resolution_m=50.0)
        chart_html = mod._comparison_figure([result])

        assert "50" in chart_html
        assert "m)" in chart_html or "50m" in chart_html

    def test_summary_table_missing_resolution_shows_placeholder(self, mod, tmp_path):
        result = _fake_result()
        result.pop("resolution_m", None)
        out_path = tmp_path / "report.html"
        mod.build_report([result], out_path)
        doc = out_path.read_text(encoding="utf-8")

        assert "Resolution" in doc
        assert "—" in doc


class TestAreaPatternFigureResolutionStamp:
    def test_bubble_chart_hovertext_includes_resolution(self, mod):
        result = _fake_result(resolution_m=50.0)
        chart_html = mod._area_pattern_figure([result])

        assert "50" in chart_html
        assert "m)" in chart_html or "50m" in chart_html

    def test_flagged_point_marker_differs_from_unflagged(self, mod):
        flagged = _fake_result(
            spec=_FakeSpec(key="flagged_catchment", display_name="Flagged Catchment"),
            pattern_claim_excluded=True,
        )
        unflagged = _fake_result(
            spec=_FakeSpec(key="ok_catchment", display_name="OK Catchment"),
            pattern_claim_excluded=False,
        )
        chart_html = mod._area_pattern_figure([flagged, unflagged])

        # Extract the embedded traces array (second Plotly.newPlot argument)
        # and compare per-point marker line styling -- flagged points must
        # be visually distinguishable. Traces is a self-contained JSON array
        # (unlike the layout/config args, which include bare JS keys), so it
        # can be parsed directly by locating its matching brackets.
        marker_start = chart_html.index('"marker": {')
        line_key_start = chart_html.index('"line": {', marker_start)
        obj_start = chart_html.index("{", line_key_start)
        obj_end = chart_html.index("}", obj_start) + 1
        line_obj = json.loads(chart_html[obj_start:obj_end])
        line_colors = line_obj["color"]
        line_widths = line_obj["width"]

        assert line_colors[0] != line_colors[1]
        assert line_widths[0] != line_widths[1]

    def test_flagged_point_hovertext_contains_flag_indicator(self, mod):
        result = _fake_result(pattern_claim_excluded=True)
        chart_html = mod._area_pattern_figure([result])

        assert "flagged" in chart_html.lower()

    def test_unflagged_point_hovertext_has_no_flag_indicator(self, mod):
        result = _fake_result(pattern_claim_excluded=False)
        chart_html = mod._area_pattern_figure([result])

        # The chart's static title legend always mentions "resolution-flagged"
        # (it explains what the red outline means), so check the per-point
        # hovertext specifically rather than the whole HTML blob.
        hovertext_start = chart_html.index('"hovertext": [') + len('"hovertext": ')
        hovertext_end = chart_html.index("]", hovertext_start) + 1
        hovertext = json.loads(chart_html[hovertext_start:hovertext_end])
        assert not any("resolution-flagged" in t.lower() for t in hovertext)

    def test_bubble_chart_handles_missing_new_keys_without_crash(self, mod):
        result = _fake_result()
        for key in ("resolution_m", "pattern_claim_excluded"):
            result.pop(key, None)

        chart_html = mod._area_pattern_figure([result])
        assert "chart-area-pattern" in chart_html
