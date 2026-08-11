"""Contract tests for compact, display-only AOI contexts."""

import importlib
import json
import sys
from dataclasses import FrozenInstanceError

import pytest


def _geopandas_and_shapes():
    geopandas = pytest.importorskip("geopandas")
    from shapely.geometry import LineString, MultiPolygon, Polygon, box, shape

    return geopandas, LineString, MultiPolygon, Polygon, box, shape


def _coordinate_count(geometry):
    coordinates = geometry["coordinates"]

    def count(value):
        if value and isinstance(value[0], (float, int)):
            return 1
        return sum(count(child) for child in value)

    return count(coordinates)


def test_module_imports_without_geopandas_and_builder_then_raises(monkeypatch):
    """Removing the optional dependency must not prevent import, only use."""
    module_name = "hydroseason._aoi_context"
    monkeypatch.delitem(sys.modules, module_name, raising=False)
    monkeypatch.setitem(sys.modules, "geopandas", None)

    module = importlib.import_module(module_name)

    with pytest.raises(ImportError, match="geopandas"):
        module.build_aoi_context(object())


def test_builds_projected_polygon_with_original_wgs84_bounds_and_immutable_fields():
    """Changing transformed bounds or dataclass mutability must break this."""
    geopandas, _, _, _, box, _ = _geopandas_and_shapes()
    from hydroseason._aoi_context import AOIContext, build_aoi_context

    source = geopandas.GeoDataFrame(
        {"secret": ["never serialize"]},
        geometry=[box(0, 0, 111_319.490793, 111_325.142866)],
        crs="EPSG:3857",
    )

    context = build_aoi_context(source)
    payload = json.loads(context.geojson)

    assert isinstance(context, AOIContext)
    assert context.bounds_wgs84 == pytest.approx((0.0, 0.0, 1.0, 1.0), abs=1e-6)
    assert context.display_name == "HydroSeason AOI"
    assert context.feature_count == 1
    assert payload["features"][0]["geometry"]["type"] == "Polygon"
    assert payload["features"][0]["properties"] == {}
    with pytest.raises(FrozenInstanceError):
        context.display_name = "changed"


def test_preserves_polygon_and_multipolygon_features_in_row_order():
    """Flattening or reordering AOI rows must break this."""
    geopandas, _, MultiPolygon, _, box, _ = _geopandas_and_shapes()
    from hydroseason._aoi_context import build_aoi_context

    source = geopandas.GeoDataFrame(
        geometry=[
            box(115, -32, 116, -31),
            MultiPolygon([box(117, -32, 118, -31), box(119, -32, 120, -31)]),
        ],
        crs="EPSG:4326",
    )

    payload = json.loads(build_aoi_context(source, simplify_deg=None).geojson)

    assert [feature["geometry"]["type"] for feature in payload["features"]] == [
        "Polygon",
        "MultiPolygon",
    ]


def test_strips_source_properties_uses_exact_labels_and_normalizes_display_name():
    """Leaking source fields or changing labels must break this."""
    geopandas, _, _, _, box, _ = _geopandas_and_shapes()
    from hydroseason._aoi_context import build_aoi_context

    source = geopandas.GeoDataFrame(
        {"token": ["secret-a", "secret-b"], "name": ["one", "two"]},
        geometry=[box(0, 0, 1, 1), box(2, 2, 3, 3)],
        crs="EPSG:4326",
    )

    context = build_aoi_context(source, display_name="  Named AOI  ", labels=["a", "b"])
    payload = json.loads(context.geojson)

    assert context.display_name == "Named AOI"
    assert [feature["properties"] for feature in payload["features"]] == [
        {"id": "a"},
        {"id": "b"},
    ]
    assert "secret-a" not in context.geojson
    assert "secret-b" not in context.geojson


def test_rounds_coordinates_and_emits_deterministic_compact_json():
    """A non-canonical JSON encoding or unrounded coordinate must break this."""
    geopandas, _, _, Polygon, _, _ = _geopandas_and_shapes()
    from hydroseason._aoi_context import build_aoi_context

    source = geopandas.GeoDataFrame(
        geometry=[
            Polygon(
                [
                    (115.123456789, -31.987654321),
                    (115.223456789, -31.987654321),
                    (115.223456789, -31.887654321),
                    (115.123456789, -31.987654321),
                ]
            )
        ],
        crs="EPSG:4326",
    )

    first = build_aoi_context(source, simplify_deg=None).geojson
    second = build_aoi_context(source, simplify_deg=None).geojson
    payload = json.loads(first)
    coordinate = payload["features"][0]["geometry"]["coordinates"][0][0]

    assert first == second
    assert first == json.dumps(payload, separators=(",", ":"), sort_keys=True)
    assert coordinate == [115.123457, -31.987654]


@pytest.mark.parametrize(
    "factory, error",
    [
        (lambda geopandas, _line, _multi, _polygon, _box: "not-a-geodataframe", TypeError),
        (lambda geopandas, _line, _multi, _polygon, box: geopandas.GeoDataFrame(geometry=[box(0, 0, 1, 1)]), ValueError),
        (lambda geopandas, _line, _multi, _polygon, _box: geopandas.GeoDataFrame(geometry=[], crs="EPSG:4326"), ValueError),
        (lambda geopandas, _line, _multi, _polygon, _box: geopandas.GeoDataFrame(geometry=[None], crs="EPSG:4326"), ValueError),
        (lambda geopandas, _line, _multi, Polygon, _box: geopandas.GeoDataFrame(geometry=[Polygon([(0, 0), (1, 1), (1, 0), (0, 1)])], crs="EPSG:4326"), ValueError),
        (lambda geopandas, LineString, _multi, _polygon, _box: geopandas.GeoDataFrame(geometry=[LineString([(0, 0), (1, 1)])], crs="EPSG:4326"), ValueError),
    ],
)
def test_rejects_invalid_or_non_polygon_aoi_inputs(factory, error):
    """Removing an AOI validity guard must break one of these cases."""
    geopandas, line, multi, polygon, box, _ = _geopandas_and_shapes()
    from hydroseason._aoi_context import build_aoi_context

    with pytest.raises(error):
        build_aoi_context(factory(geopandas, line, multi, polygon, box))


def test_rejects_label_count_that_does_not_match_feature_rows():
    """Ignoring label row alignment must break this."""
    geopandas, _, _, _, box, _ = _geopandas_and_shapes()
    from hydroseason._aoi_context import build_aoi_context

    source = geopandas.GeoDataFrame(geometry=[box(0, 0, 1, 1)], crs="EPSG:4326")

    with pytest.raises(ValueError, match="labels"):
        build_aoi_context(source, labels=["first", "second"])


def test_default_display_simplification_reduces_dense_boundary_without_changing_bounds():
    """Removing topology-preserving display simplification must break this."""
    numpy = pytest.importorskip("numpy")
    geopandas, _, _, Polygon, _, shape = _geopandas_and_shapes()
    from hydroseason._aoi_context import build_aoi_context

    x_values = numpy.linspace(0.0, 10.0, 20_000)
    top = [(float(x), float(1.0 + 0.02 * numpy.sin(200.0 * x))) for x in x_values]
    dense_polygon = Polygon(top + [(10.0, 0.0), (0.0, 0.0)])
    source = geopandas.GeoDataFrame(geometry=[dense_polygon], crs="EPSG:4326")

    context = build_aoi_context(source)
    geometry = json.loads(context.geojson)["features"][0]["geometry"]

    assert _coordinate_count(geometry) <= len(dense_polygon.exterior.coords) / 10
    assert shape(geometry).is_valid and not shape(geometry).is_empty
    assert context.bounds_wgs84 == pytest.approx(dense_polygon.bounds)


def test_warns_but_returns_when_geojson_exceeds_size_limit():
    """Turning size control into a fatal error or suppressing its warning breaks this."""
    geopandas, _, _, _, box, _ = _geopandas_and_shapes()
    from hydroseason._aoi_context import build_aoi_context

    source = geopandas.GeoDataFrame(geometry=[box(0, 0, 1, 1)], crs="EPSG:4326")

    with pytest.warns(UserWarning, match=r"bytes.*simplify_deg=None"):
        context = build_aoi_context(source, simplify_deg=None, max_geojson_bytes=1)

    assert len(context.geojson.encode("utf-8")) > 1
