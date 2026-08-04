import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence

import pandas as pd


@dataclass(frozen=True)
class CatchmentSpec:
    key: str
    display_name: str
    river: str
    region: str


CATCHMENTS = (
    CatchmentSpec("gilbert_river_qld", "Gilbert River (QLD)", "Gilbert River", "QLD"),
    CatchmentSpec("fitzroy_river_wa", "Fitzroy River (WA)", "Fitzroy River", "WA Kimberley"),
    CatchmentSpec("moonie_river_qld_nsw", "Moonie River (QLD/NSW)", "Moonie River", "QLD/NSW"),
    CatchmentSpec("lachlan_river_nsw", "Lachlan River (NSW)", "Lachlan River", "NSW"),
    CatchmentSpec("paroo_river_qld_nsw", "Paroo River (QLD/NSW)", "Paroo River", "QLD/NSW"),
    CatchmentSpec("daly_river_nt", "Daly River (NT)", "Daly River", "NT"),
)


@dataclass
class LowerReachWindow:
    catchment_key: str
    lower_hydroid: object
    lower_point: object
    square_aoi: object
    analysis_aoi: object
    square_bounds_projected: tuple[float, float, float, float]
    analysis_bounds_wgs84: tuple[float, float, float, float]


def _import_geopandas():
    try:
        import geopandas as gpd
    except ImportError as exc:  # pragma: no cover
        raise ImportError("AOI tools require geopandas.") from exc
    return gpd


def _geometry_union(geometries):
    """Compatibility wrapper for shapely/geopandas union naming drift."""
    if hasattr(geometries, "union_all"):
        return geometries.union_all()
    return geometries.unary_union


def _longest_linestring(geom):
    """Return a LineString-like part from LineString/MultiLineString geometry."""
    if geom.geom_type == "LineString":
        return geom
    if geom.geom_type == "MultiLineString":
        return max(geom.geoms, key=lambda part: part.length)
    raise ValueError(f"Expected stream line geometry, got {geom.geom_type!r}.")


def _downstream_endpoint(geom):
    """Use AHGF line coordinate order: last coordinate is downstream endpoint."""
    from shapely.geometry import Point

    line = _longest_linestring(geom)
    x, y = list(line.coords)[-1]
    return Point(float(x), float(y))


def _candidate_streams(streams):
    if "hierarchy" not in streams.columns:
        return streams
    major = streams[streams["hierarchy"].astype(str).str.casefold() == "major"]
    return major if not major.empty else streams


def select_lower_reach(streams):
    """Pick lower/outlet reach: major outlet with largest upstream area."""
    if streams.empty:
        raise ValueError("No stream reaches available for lower-reach selection.")

    pool = _candidate_streams(streams)
    outlets = pool.iloc[0:0]

    if {"hydroid", "nextdownid"}.issubset(streams.columns):
        hydroids = set(streams["hydroid"].dropna().tolist())
        outlets = pool[~pool["nextdownid"].isin(hydroids)]
        if outlets.empty:
            outlets = streams[~streams["nextdownid"].isin(hydroids)]

    candidates = outlets if not outlets.empty else pool
    candidates = candidates.copy()
    if "upstrdarea" in candidates.columns:
        candidates["_sort_upstream_area"] = pd.to_numeric(
            candidates["upstrdarea"], errors="coerce"
        ).fillna(-1.0)
    else:
        candidates["_sort_upstream_area"] = -1.0
    candidates["_sort_length"] = candidates.geometry.length
    chosen = candidates.sort_values(
        ["_sort_upstream_area", "_sort_length"], ascending=[False, False]
    ).iloc[0]
    return chosen


def build_lower_reach_window(
    catchment_key: str,
    boundary,
    streams,
    *,
    side_km: float = 50.0,
    output_crs: int | str = 3577,
) -> LowerReachWindow:
    """Build catchment-clipped 50 km square AOI around inferred lower reach."""
    gpd = _import_geopandas()
    from shapely.geometry import box

    boundary_proj = boundary.to_crs(output_crs)
    streams_proj = streams.to_crs(output_crs)
    lower_reach = select_lower_reach(streams_proj)
    lower_point = _downstream_endpoint(lower_reach.geometry)

    half_side_m = side_km * 1_000.0 / 2.0
    square = box(
        lower_point.x - half_side_m,
        lower_point.y - half_side_m,
        lower_point.x + half_side_m,
        lower_point.y + half_side_m,
    )
    square_aoi = gpd.GeoDataFrame({"kind": ["lower_reach_square"]}, geometry=[square], crs=output_crs)

    boundary_geom = _geometry_union(boundary_proj.geometry)
    clipped = square.intersection(boundary_geom)
    if clipped.is_empty:
        clipped = square
    analysis_aoi = gpd.GeoDataFrame(
        {"kind": ["lower_reach_square_clipped_to_catchment"]},
        geometry=[clipped],
        crs=output_crs,
    )
    analysis_bounds_wgs84 = tuple(float(v) for v in analysis_aoi.to_crs(4326).total_bounds)

    return LowerReachWindow(
        catchment_key=catchment_key,
        lower_hydroid=lower_reach.get("hydroid", None),
        lower_point=lower_point,
        square_aoi=square_aoi,
        analysis_aoi=analysis_aoi,
        square_bounds_projected=tuple(float(v) for v in square_aoi.total_bounds),
        analysis_bounds_wgs84=analysis_bounds_wgs84,
    )


@dataclass(frozen=True)
class StudyAOI:
    key: str
    display_name: str
    catchment_key: str
    kind: Literal["lower50km", "full"]
    path: Path


FULL_BOUNDARY_KEYS = (
    "gilbert_river_qld",
    "fitzroy_river_wa",
    "moonie_river_qld_nsw",
)


def _read_inputs(catchments_dir: Path, key: str):
    gpd = _import_geopandas()
    boundary_path = catchments_dir / f"{key}_boundary.parquet"
    streams_path = catchments_dir / f"{key}_streams.parquet"
    if not boundary_path.exists():
        raise FileNotFoundError(f"Missing boundary fixture: {boundary_path}")
    if not streams_path.exists():
        raise FileNotFoundError(f"Missing streams fixture: {streams_path}")
    return gpd.read_parquet(boundary_path), gpd.read_parquet(streams_path)


def _write_aoi(gpd, df, out_path: Path, force: bool):
    if out_path.exists() and not force:
        # Check digest
        new_json = df.to_crs(4326).to_json()
        new_digest = hashlib.sha256(new_json.encode("utf-8")).hexdigest()
        old_json = out_path.read_text(encoding="utf-8")
        old_digest = hashlib.sha256(old_json.encode("utf-8")).hexdigest()
        if new_digest == old_digest:
            return
    
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_crs(4326).to_file(out_path, driver="GeoJSON")


def study_aois(catchments_dir: Path, output_dir: Path, *, force: bool = False) -> Sequence[StudyAOI]:
    gpd = _import_geopandas()
    out = []

    # 6 lower50km windows
    for spec in CATCHMENTS:
        key = f"{spec.key}__lower50km"
        path = output_dir / f"{key}.geojson"
        
        boundary, streams = _read_inputs(catchments_dir, spec.key)
        window = build_lower_reach_window(spec.key, boundary, streams, side_km=50.0)
        
        if window.analysis_aoi.empty:
            raise ValueError(f"Empty geometry for {key}")
            
        _write_aoi(gpd, window.analysis_aoi, path, force)
        
        out.append(StudyAOI(
            key=key,
            display_name=f"{spec.display_name} (lower 50km)",
            catchment_key=spec.key,
            kind="lower50km",
            path=path,
        ))

    # 3 full boundaries
    for catchment_key in FULL_BOUNDARY_KEYS:
        spec = next(s for s in CATCHMENTS if s.key == catchment_key)
        key = f"{spec.key}__full"
        path = output_dir / f"{key}.geojson"
        
        boundary, _ = _read_inputs(catchments_dir, spec.key)
        if boundary.empty:
            raise ValueError(f"Empty boundary for {key}")
            
        # Add kind attribute to be consistent
        boundary = boundary.copy()
        boundary["kind"] = "full_boundary"
        
        _write_aoi(gpd, boundary, path, force)
        
        out.append(StudyAOI(
            key=key,
            display_name=f"{spec.display_name} (full)",
            catchment_key=spec.key,
            kind="full",
            path=path,
        ))

    return tuple(out)
