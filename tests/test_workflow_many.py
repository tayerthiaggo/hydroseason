"""Contract tests for row-preserving multi-AOI preflight."""

import importlib
import sys
from dataclasses import FrozenInstanceError

import pytest


def _geopandas_and_shapes():
    geopandas = pytest.importorskip("geopandas")
    from shapely.geometry import MultiPolygon, Polygon, box

    return geopandas, MultiPolygon, Polygon, box


def _frame(*, ids=None, geometries=None, crs="EPSG:4326"):
    geopandas, _multi, _polygon, box = _geopandas_and_shapes()
    if geometries is None:
        geometries = [box(115, -32, 116, -31), box(117, -32, 118, -31)]
    data = {} if ids is None else {"aoi_id": ids}
    return geopandas.GeoDataFrame(data, geometry=geometries, crs=crs)


def _prepare(frame, tmp_path, **kwargs):
    from hydroseason.batch import _prepare_batch_aois

    return _prepare_batch_aois(
        frame,
        output_dir=tmp_path / "output",
        cache_dir=tmp_path / "cache",
        **kwargs,
    )


def test_batch_outcomes_are_immutable_and_partitioned_in_source_order():
    """Changing tuple order, filtering, or outcome immutability must break this."""
    from hydroseason.batch import HydroSeasonAOIOutcome, HydroSeasonBatchResult

    first = HydroSeasonAOIOutcome("first", 0, object(), None, None)
    second = HydroSeasonAOIOutcome("second", 1, None, "ValueError", "bad input")
    third = HydroSeasonAOIOutcome("third", 2, object(), None, None)
    batch = HydroSeasonBatchResult((first, second, third))

    assert batch.outcomes == (first, second, third)
    assert batch.succeeded == (first, third)
    assert batch.failed == (second,)
    assert first.succeeded is True
    assert second.succeeded is False
    with pytest.raises(FrozenInstanceError):
        first.id = "changed"


def test_outcome_requires_exactly_a_result_or_complete_error_details():
    """Dropping either side of the result/error invariant must break this."""
    from hydroseason.batch import HydroSeasonAOIOutcome

    with pytest.raises(ValueError, match="result or complete error details"):
        HydroSeasonAOIOutcome("missing", 0, None, None, None)
    with pytest.raises(ValueError, match="result or complete error details"):
        HydroSeasonAOIOutcome("mixed", 0, object(), "ValueError", "bad")
    with pytest.raises(ValueError, match="result or complete error details"):
        HydroSeasonAOIOutcome("partial-success", 0, object(), "ValueError", None)
    with pytest.raises(ValueError, match="result or complete error details"):
        HydroSeasonAOIOutcome("partial", 0, None, "ValueError", None)


def test_raise_for_failures_reports_every_failure_without_losing_successes():
    """Reporting only the first error or discarding successes must break this."""
    from hydroseason.batch import (
        HydroSeasonAOIOutcome,
        HydroSeasonBatchError,
        HydroSeasonBatchResult,
    )

    success = HydroSeasonAOIOutcome("kept", 0, object(), None, None)
    batch = HydroSeasonBatchResult(
        (
            success,
            HydroSeasonAOIOutcome("alpha", 1, None, "ValueError", "bad geometry"),
            HydroSeasonAOIOutcome("beta", 2, None, "RuntimeError", "unavailable"),
        )
    )

    with pytest.raises(HydroSeasonBatchError) as raised:
        batch.raise_for_failures()

    assert "alpha" in str(raised.value)
    assert "ValueError" in str(raised.value)
    assert "beta" in str(raised.value)
    assert "RuntimeError" in str(raised.value)
    assert batch.succeeded == (success,)


def test_batch_module_import_does_not_eagerly_import_geopandas(monkeypatch):
    """A module-level optional geospatial import must make this fail."""
    monkeypatch.delitem(sys.modules, "hydroseason.batch", raising=False)
    monkeypatch.setitem(sys.modules, "geopandas", None)

    module = importlib.import_module("hydroseason.batch")

    assert module.__name__ == "hydroseason.batch"


def test_preflight_loads_path_and_geodataframe_once_each(monkeypatch, tmp_path):
    """Reloading the source per row must make either call count fail."""
    from hydroseason import io
    from hydroseason.batch import _prepare_batch_aois

    source = _frame(ids=["alpha", "beta"])
    calls = []

    def fake_load_aoi(value):
        calls.append(value)
        return source.copy()

    monkeypatch.setattr(io, "load_aoi", fake_load_aoi)
    path_items = _prepare_batch_aois(
        "areas.geojson", output_dir=tmp_path / "path-output", id_col="aoi_id"
    )
    frame_items = _prepare_batch_aois(
        source, output_dir=tmp_path / "frame-output", id_col="aoi_id"
    )

    assert calls == ["areas.geojson", source]
    assert len(path_items) == len(frame_items) == 2


@pytest.mark.parametrize(
    "frame",
    [
        pytest.param(_frame(crs=None), id="missing-crs"),
        pytest.param(_frame(geometries=[]), id="empty"),
        pytest.param(
            _frame(geometries=[None]),
            id="empty-geometry",
        ),
        pytest.param(
            _frame(
                geometries=[
                    _geopandas_and_shapes()[2]([(0, 0), (1, 1), (1, 0), (0, 1)])
                ]
            ),
            id="invalid-geometry",
        ),
    ],
)
def test_preflight_rejects_missing_crs_or_invalid_rows(frame, tmp_path):
    """Allowing invalid source data into batch work must break this."""
    with pytest.raises(ValueError):
        _prepare(frame, tmp_path)


def test_one_multipolygon_row_stays_one_prepared_item(tmp_path):
    """Exploding a MultiPolygon into many work items must break this."""
    _geopandas, multi_polygon, _polygon, box = _geopandas_and_shapes()
    frame = _frame(
        geometries=[multi_polygon([box(115, -32, 116, -31), box(117, -32, 118, -31)])]
    )

    items = _prepare(frame, tmp_path)

    assert len(items) == 1
    assert len(items[0].gdf) == 1
    assert items[0].gdf.geometry.iloc[0].geom_type == "MultiPolygon"


def test_scattered_source_rows_remain_separate_without_unioning(tmp_path):
    """Combining rows before scheduling must break source-position isolation."""
    _geopandas, _multi, _polygon, box = _geopandas_and_shapes()
    frame = _frame(
        geometries=[
            box(115, -32, 116, -31),
            box(130, -20, 131, -19),
            box(140, -10, 141, -9),
        ]
    )

    items = _prepare(frame, tmp_path)

    assert [item.source_position for item in items] == [0, 1, 2]
    assert [len(item.gdf) for item in items] == [1, 1, 1]
    assert [item.gdf.geometry.iloc[0] for item in items] == list(frame.geometry)


@pytest.mark.parametrize(
    "frame,id_col",
    [
        pytest.param(_frame(), "missing", id="missing-column"),
        pytest.param(_frame(ids=["alpha", None]), "aoi_id", id="null"),
        pytest.param(_frame(ids=["alpha", "   "]), "aoi_id", id="blank"),
        pytest.param(_frame(ids=["alpha", "alpha"]), "aoi_id", id="duplicate"),
    ],
)
def test_preflight_rejects_unusable_explicit_ids(frame, id_col, tmp_path):
    """Missing, ambiguous, or duplicate row IDs must never reach workers."""
    with pytest.raises(ValueError):
        _prepare(frame, tmp_path, id_col=id_col)


def test_preflight_generates_stable_ids_and_child_paths_without_creating_them(tmp_path):
    """Changing generated IDs, child layout, or preflight writes must break this."""
    items = _prepare(_frame(), tmp_path)

    assert [(item.id, item.safe_id, item.source_position) for item in items] == [
        ("aoi-0001", "aoi-0001", 0),
        ("aoi-0002", "aoi-0002", 1),
    ]
    assert [item.output_dir for item in items] == [
        tmp_path / "output" / "aoi-0001",
        tmp_path / "output" / "aoi-0002",
    ]
    assert [item.cache_dir for item in items] == [
        tmp_path / "cache" / "aoi-0001",
        tmp_path / "cache" / "aoi-0002",
    ]
    assert not (tmp_path / "output").exists()
    assert not (tmp_path / "cache").exists()


def test_preflight_rejects_safe_stem_collisions_before_touching_existing_child_dirs(tmp_path):
    """Suffixing colliding IDs or deleting existing output must break this."""
    frame = _frame(ids=["A/B", "A B"])
    existing = tmp_path / "output" / "a-b"
    existing.mkdir(parents=True)
    sentinel = existing / "keep.txt"
    sentinel.write_text("do not overwrite", encoding="utf-8")

    with pytest.raises(ValueError, match="safe"):
        _prepare(frame, tmp_path, id_col="aoi_id")

    assert sentinel.read_text(encoding="utf-8") == "do not overwrite"
