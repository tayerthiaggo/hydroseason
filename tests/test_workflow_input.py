import pandas as pd
import pytest

from hydroseason._workflow_input import resolve_water_input


def _extent_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {"extent_pct": [10.0, 20.0, 30.0], "invalid_pct": [0.0, 5.0, 0.0]},
        index=pd.date_range("2020-01-01", periods=3, freq="MS"),
    )


def test_csv_and_dataframe_resolve_to_equivalent_extent(tmp_path):
    frame = _extent_frame()
    csv_path = tmp_path / "extent.csv"
    frame.rename_axis("date").reset_index().to_csv(csv_path, index=False)

    from_csv = resolve_water_input(csv_path)
    from_frame = resolve_water_input(frame)

    assert from_csv.source_kind == "extent_csv"
    assert from_frame.source_kind == "extent_dataframe"
    pd.testing.assert_frame_equal(from_csv.extent, from_frame.extent)


def test_extent_without_invalid_pct_is_treated_as_quality_screened():
    frame = _extent_frame().drop(columns="invalid_pct")
    resolved = resolve_water_input(frame)

    assert resolved.extent["invalid_pct"].tolist() == [0.0, 0.0, 0.0]


def test_none_source_requires_dea_arguments():
    with pytest.raises(ValueError, match="aoi, start_date, and end_date"):
        resolve_water_input(None)


def test_none_source_calls_dea_loader(monkeypatch, tmp_path):
    expected = _extent_frame()
    calls = {}

    def fake_loader(stac_url, collection, aoi, start_date, end_date, *, cache_dir):
        calls.update(
            stac_url=stac_url,
            collection=collection,
            aoi=aoi,
            start_date=start_date,
            end_date=end_date,
            cache_dir=cache_dir,
        )
        return expected

    monkeypatch.setattr(
        "hydroseason._workflow_input.load_wofs_monthly_extent", fake_loader
    )
    resolved = resolve_water_input(
        None,
        aoi="aoi.geojson",
        start_date="2020-01-01",
        end_date="2020-03-01",
        cache_dir=tmp_path / "cache",
    )

    assert resolved.source_kind == "dea_wofs"
    pd.testing.assert_frame_equal(resolved.extent, expected)
    assert calls["collection"] == "ga_ls_wo_3"


def _mask_array():
    xr = pytest.importorskip("xarray")
    import numpy as np

    values = np.array(
        [
            [[1, 0], [0, -2]],
            [[1, 1], [-1, -2]],
            [[0, 0], [1, -2]],
        ],
        dtype=np.int8,
    )
    return xr.DataArray(
        values,
        dims=("time", "y", "x"),
        coords={
            "time": pd.date_range("2020-01-01", periods=3, freq="MS"),
            "y": [1, 0],
            "x": [0, 1],
        },
        name="water_mask",
    )


def test_dataarray_dataset_netcdf_and_zarr_match(tmp_path):
    pytest.importorskip("xarray")
    mask = _mask_array()
    dataset = mask.to_dataset(name="water_mask")
    netcdf_path = tmp_path / "masks.nc"
    zarr_path = tmp_path / "masks.zarr"
    dataset.to_netcdf(netcdf_path)
    dataset.to_zarr(zarr_path, mode="w")

    resolved = [
        resolve_water_input(mask),
        resolve_water_input(dataset),
        resolve_water_input(netcdf_path),
        resolve_water_input(zarr_path),
    ]

    assert [item.source_kind for item in resolved] == [
        "xarray_dataarray",
        "xarray_dataset",
        "netcdf_mask",
        "zarr_mask",
    ]
    for item in resolved[1:]:
        pd.testing.assert_frame_equal(item.extent, resolved[0].extent)


def test_dataset_variable_selection_is_explicit_when_ambiguous():
    xr = pytest.importorskip("xarray")
    mask = _mask_array()
    dataset = xr.Dataset({"first": mask, "second": mask})

    with pytest.raises(ValueError, match="available variables.*first.*second"):
        resolve_water_input(dataset)

    selected = resolve_water_input(dataset, water_mask_variable="second")
    assert selected.source_kind == "xarray_dataset"


def test_mask_rejects_missing_dimensions_and_unknown_codes():
    xr = pytest.importorskip("xarray")
    import numpy as np

    missing_x = xr.DataArray(
        np.zeros((2, 2), dtype=np.int8),
        dims=("time", "y"),
        coords={"time": pd.date_range("2020-01-01", periods=2, freq="MS")},
    )
    with pytest.raises(ValueError, match="time, y, and x"):
        resolve_water_input(missing_x)

    invalid = _mask_array().copy()
    invalid.values[0, 0, 0] = 9
    with pytest.raises(ValueError, match="canonical values"):
        resolve_water_input(invalid)


def test_mask_rejects_duplicate_month_timestamps():
    duplicate = _mask_array().assign_coords(
        time=["2020-01-01", "2020-01-20", "2020-03-01"]
    )
    with pytest.raises(ValueError, match="Duplicate month timestamps.*2020-01"):
        resolve_water_input(duplicate)


def test_local_date_bounds_subset_and_complete_months():
    mask = _mask_array().isel(time=[0, 2])
    resolved = resolve_water_input(
        mask, start_date="2020-01-01", end_date="2020-03-01"
    )
    assert resolved.extent.index.tolist() == list(
        pd.date_range("2020-01-01", "2020-03-01", freq="MS")
    )
    assert resolved.extent.loc["2020-02-01", "invalid_pct"] == 100.0
