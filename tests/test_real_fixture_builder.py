import pandas as pd

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
