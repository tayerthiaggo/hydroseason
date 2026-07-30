from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

from scripts import build_real_extent_fixture
from scripts.build_real_extent_fixture import add_provenance


def test_add_provenance_preserves_counts_and_identifies_source():
    frame = pd.DataFrame({
        "n_water": [2], "n_aoi": [10], "n_valid": [8], "n_invalid": [2],
        "extent_pct": [25.0], "invalid_pct": [20.0],
    }, index=pd.to_datetime(["2020-01-01"]))
    result = add_provenance(frame, source="DEA ga_ls_wo_3", aoi="data/a.geojson")
    assert result.index.name == "date"
    assert result.loc[pd.Timestamp("2020-01-01"), "source"] == "DEA ga_ls_wo_3"
    assert result.loc[pd.Timestamp("2020-01-01"), "aoi"] == "data/a.geojson"


def test_build_passes_resolution_to_loader(monkeypatch, tmp_path):
    calls = {}
    frame = pd.DataFrame({
        "n_water": [2], "n_aoi": [10], "n_valid": [8], "n_invalid": [2],
        "extent_pct": [25.0], "invalid_pct": [20.0],
    }, index=pd.to_datetime(["2020-01-01"]))

    monkeypatch.setattr(build_real_extent_fixture, "load_aoi", lambda path: "aoi")

    def fake_loader(*args, **kwargs):
        calls.update(kwargs)
        return frame

    monkeypatch.setattr(build_real_extent_fixture, "load_wofs_monthly_extent", fake_loader)

    build_real_extent_fixture.build(
        tmp_path / "a.geojson",
        tmp_path / "extent.csv",
        "2020-01-01",
        "2020-01-01",
        tmp_path / "cache",
        resolution=300,
    )

    assert calls["resolution"] == 300


def test_build_propagates_native_tiled_defaults(tmp_path):
    """Step 1: Test that build() passes resolution and tile_pixels through to load_wofs_monthly_extent."""
    with patch("scripts.build_real_extent_fixture.load_aoi") as mock_load_aoi, \
         patch("scripts.build_real_extent_fixture.load_wofs_monthly_extent") as mock_load_wofs, \
         patch("scripts.build_real_extent_fixture.pd.date_range") as mock_date_range:

        # Setup mocks
        mock_load_aoi.return_value = MagicMock()
        test_index = pd.to_datetime(["2020-01-01"])
        mock_load_wofs.return_value = pd.DataFrame({
            "n_water": [1],
            "n_aoi": [10],
            "n_valid": [9],
            "n_invalid": [0],
            "extent_pct": [10.0],
            "invalid_pct": [0.0],
        }, index=test_index)
        # Make date_range return an index that equals the mock DataFrame's index
        mock_date_range.return_value = test_index

        output_path = tmp_path / "output" / "test.csv"

        # Call with explicit resolution and tile_pixels
        build_real_extent_fixture.build(
            Path("data/catchments/example_boundary.geojson"),
            output_path,
            "2020-01-01",
            "2020-12-31",
            Path("cache"),
            resolution=30,
            tile_pixels=1024,
        )

        # Extract the call arguments
        calls = mock_load_wofs.call_args.kwargs

        # Step 1 assertions from the brief
        assert calls["crs"] == build_real_extent_fixture.DEA_ALBERS_CRS
        assert calls["resolution"] == 30
        assert calls["tile_pixels"] == 1024


def test_cli_defaults_to_native_tiled_loading():
    """Step 2: Test that build_parser() provides defaults for resolution and tile_pixels."""
    args = build_real_extent_fixture.build_parser().parse_args([
        "--aoi", "data/catchments/example_boundary.geojson",
        "--output", "output/example.csv",
    ])
    assert args.resolution == 30.0
    assert args.tile_pixels == 1024
