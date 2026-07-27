"""Tests for reusable AOI construction logic."""

from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import LineString, box

from hydroseason._study_aois import (
    CATCHMENTS,
    FULL_BOUNDARY_KEYS,
    study_aois,
)


def test_study_aois_produces_expected_records(monkeypatch, tmp_path):
    # Mock _read_inputs to return toy geodataframes
    def fake_read_inputs(catchments_dir, key):
        boundary = gpd.GeoDataFrame(
            {"area_km2": [200.0]},
            geometry=[box(0, -1_000, 100_000, 1_000)],
            crs="EPSG:3577",
        )
        # Mock streams with properties expected by select_lower_reach
        streams = gpd.GeoDataFrame(
            {
                "hydroid": [1],
                "nextdownid": [999],
                "hierarchy": ["Major"],
                "upstrdarea": [100.0],
            },
            geometry=[LineString([(0, 0), (10_000, 0)])],
            crs="EPSG:3577",
        )
        return boundary, streams

    def fake_write_aoi(gpd_mod, df, out_path, force):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr("hydroseason._study_aois._read_inputs", fake_read_inputs)
    monkeypatch.setattr("hydroseason._study_aois._write_aoi", fake_write_aoi)
    
    # Run the generator function
    aois = study_aois(tmp_path / "in", tmp_path / "out")
    
    assert len(aois) == len(CATCHMENTS) + len(FULL_BOUNDARY_KEYS)
    
    lower_aois = [a for a in aois if a.kind == "lower50km"]
    full_aois = [a for a in aois if a.kind == "full"]
    
    assert len(lower_aois) == 6
    assert len(full_aois) == 3
    
    # Check keys
    for aoi in lower_aois:
        assert aoi.key.endswith("__lower50km")
        assert aoi.path == tmp_path / "out" / f"{aoi.key}.geojson"
    
    for aoi in full_aois:
        assert aoi.key.endswith("__full")
        assert aoi.path == tmp_path / "out" / f"{aoi.key}.geojson"
