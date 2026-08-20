"""Compact, dependency-light AOI display contexts."""

from __future__ import annotations

import json
import warnings
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class AOIContext:
    """Immutable AOI metadata and compact GeoJSON for display.

    ``geojson`` may be topology-preservingly simplified for display only;
    it is not the analysed footprint. ``bounds_wgs84`` always describes the
    transformed, unsimplified acquisition geometry.
    """

    geojson: str
    bounds_wgs84: tuple[float, float, float, float]
    display_name: str
    feature_count: int


def _round_coordinates(value):
    if isinstance(value, (list, tuple)):
        return [_round_coordinates(item) for item in value]
    return round(float(value), 6)


def _display_geometry(geometry, simplify_deg: float | None):
    if simplify_deg is None:
        return geometry

    simplified = geometry.simplify(simplify_deg, preserve_topology=True)
    if simplified.is_empty or not simplified.is_valid:
        return geometry
    return simplified


def build_aoi_context(
    aoi_gdf,
    *,
    display_name: str | None = None,
    labels: Sequence[str] | None = None,
    simplify_deg: float | None = 0.001,
    max_geojson_bytes: int = 512_000,
) -> AOIContext:
    """Create compact WGS84 display GeoJSON from a polygonal GeoDataFrame."""
    try:
        import geopandas as gpd
        from shapely.geometry import mapping
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise ImportError(
            "build_aoi_context requires geopandas and shapely."
        ) from exc

    if not isinstance(aoi_gdf, gpd.GeoDataFrame):
        raise TypeError("aoi_gdf must be a geopandas.GeoDataFrame.")
    if aoi_gdf.crs is None:
        raise ValueError("aoi_gdf must have a CRS.")
    if aoi_gdf.empty:
        raise ValueError("aoi_gdf must not be empty.")

    geometry = aoi_gdf.geometry
    if geometry.isna().any() or geometry.is_empty.any():
        raise ValueError("aoi_gdf must contain only non-empty geometries.")
    if not geometry.is_valid.all():
        raise ValueError("aoi_gdf must contain only valid geometries.")
    if not geometry.geom_type.isin(["Polygon", "MultiPolygon"]).all():
        raise ValueError("aoi_gdf must contain only Polygon or MultiPolygon geometries.")
    if simplify_deg is not None and simplify_deg < 0:
        raise ValueError("simplify_deg must be non-negative or None.")

    transformed = aoi_gdf.to_crs("EPSG:4326")
    bounds_wgs84 = tuple(float(value) for value in transformed.total_bounds)

    if labels is not None and len(labels) != len(transformed):
        raise ValueError("labels must contain exactly one value per AOI row.")

    normalized_name = (display_name or "").strip() or "HydroSeason AOI"
    features = []
    for index, geometry in enumerate(transformed.geometry):
        display_geometry = _display_geometry(geometry, simplify_deg)
        geometry_json = mapping(display_geometry)
        properties = {} if labels is None else {"id": labels[index]}
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": geometry_json["type"],
                    "coordinates": _round_coordinates(geometry_json["coordinates"]),
                },
                "properties": properties,
            }
        )

    geojson = json.dumps(
        {"type": "FeatureCollection", "features": features},
        separators=(",", ":"),
        sort_keys=True,
    )
    geojson_bytes = len(geojson.encode("utf-8"))
    if geojson_bytes > max_geojson_bytes:
        warnings.warn(
            (
                f"AOI GeoJSON is {geojson_bytes} bytes "
                f"(simplify_deg={simplify_deg!r}); exceeds "
                f"max_geojson_bytes={max_geojson_bytes}."
            ),
            UserWarning,
            stacklevel=2,
        )

    return AOIContext(
        geojson=geojson,
        bounds_wgs84=bounds_wgs84,
        display_name=normalized_name,
        feature_count=len(transformed),
    )
