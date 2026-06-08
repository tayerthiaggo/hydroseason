"""Australia-only SILO stress harness for HydroSeason.

The sampler is geographic only: points are stratified by latitude and longitude
bands, then HydroSeason discovers the rainfall regimes from SILO data.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from hydroseason import PipelineArtifacts, classify_rainfall
from hydroseason.fetch import get_monthly_aoi_rainfall


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "output" / "australia_rainfall_fetch_stress_test"
DEFAULT_CACHE = ROOT / "data" / "global_rainfall_fetch_stress_cache"
NATURAL_EARTH_SHP = (
    ROOT
    / "data"
    / "natural_earth"
    / "ne_110m_admin_0_countries"
    / "ne_110m_admin_0_countries.shp"
)

SAMPLE_CRS = "EPSG:8857"
N_SITES = 50
SEED = 20260608
START_YEAR = 1980
END_YEAR = 2025
AOI_SIDE_DEGREES = 0.5
INLAND_BUFFER_KM = 75.0


def latitude_band(lat: float) -> str:
    abs_lat = abs(float(lat))
    hemi = "N" if lat >= 0 else "S"
    if abs_lat < 10:
        return "equatorial"
    if abs_lat < 23.5:
        return f"tropical_{hemi}"
    if abs_lat < 35:
        return f"subtropical_{hemi}"
    if abs_lat < 55:
        return f"temperate_{hemi}"
    return f"boreal_subpolar_{hemi}"


def longitude_band(lon: float) -> str:
    value = float(lon)
    if value < 123.0:
        return "west"
    if value < 135.0:
        return "central_west"
    if value < 145.0:
        return "central_east"
    return "east"


def random_point_in_geometry(geom, rng: np.random.Generator, max_attempts: int = 1000):
    from shapely.geometry import Point

    minx, miny, maxx, maxy = geom.bounds
    for _ in range(max_attempts):
        candidate = Point(rng.uniform(minx, maxx), rng.uniform(miny, maxy))
        if geom.contains(candidate):
            return candidate
    return geom.representative_point()


def load_australia_land(natural_earth_shp: Path = NATURAL_EARTH_SHP):
    import geopandas as gpd

    if not natural_earth_shp.exists():
        raise FileNotFoundError(
            "Natural Earth country shapefile not found. Expected cached file: "
            f"{natural_earth_shp}"
        )

    land = gpd.read_file(natural_earth_shp).to_crs("EPSG:4326")
    name_col = "ADMIN" if "ADMIN" in land.columns else "NAME"
    australia = land[land[name_col].eq("Australia")].copy()
    if australia.empty:
        raise ValueError("Could not find Australia in Natural Earth countries.")

    try:
        australia["geometry"] = australia.geometry.make_valid()
    except AttributeError:
        australia["geometry"] = australia.geometry.buffer(0)
    australia = australia[~australia.geometry.isna() & ~australia.geometry.is_empty]
    return australia[[name_col, "geometry"]].rename(columns={name_col: "country"})


def prepare_inland_polygons(australia_gdf, inland_buffer_km: float):
    work = australia_gdf.to_crs(SAMPLE_CRS).copy()
    work = work.explode(ignore_index=True)
    work["geometry"] = work.geometry.buffer(-float(inland_buffer_km) * 1000.0)
    work = work[~work.geometry.isna() & ~work.geometry.is_empty].copy()
    work["area_m2"] = work.geometry.area
    return work[work["area_m2"] > 0].copy()


def build_candidate_pool(
    inland_gdf,
    *,
    n_candidates: int,
    seed: int,
    aoi_side_degrees: float,
):
    import geopandas as gpd

    rng = np.random.default_rng(seed)
    weights = inland_gdf["area_m2"].to_numpy(dtype=float)
    weights = weights / weights.sum()
    chosen = rng.choice(len(inland_gdf), size=int(n_candidates), replace=True, p=weights)

    geoms = []
    records: list[dict[str, Any]] = []
    for pos in chosen:
        row = inland_gdf.iloc[int(pos)]
        geoms.append(random_point_in_geometry(row.geometry, rng))
        records.append({"country": "Australia"})

    candidates = gpd.GeoDataFrame(records, geometry=geoms, crs=SAMPLE_CRS).to_crs(
        "EPSG:4326"
    )
    candidates["lon"] = candidates.geometry.x
    candidates["lat"] = candidates.geometry.y
    half_side = float(aoi_side_degrees) / 2.0
    candidates = candidates[
        candidates["lon"].between(112.0 + half_side, 154.0 - half_side)
        & candidates["lat"].between(-44.0 + half_side, -9.0 - half_side)
    ].copy()
    candidates["lat_band"] = candidates["lat"].map(latitude_band)
    candidates["lon_band"] = candidates["lon"].map(longitude_band)
    candidates["stratum"] = candidates["lat_band"] + " / " + candidates["lon_band"]
    return candidates.reset_index(drop=True)


def stratified_select(candidates, *, n_sites: int, seed: int):
    rng = np.random.default_rng(seed)
    shuffled = candidates.sample(frac=1.0, random_state=seed).copy()
    groups = [
        list(group.index)
        for _name, group in shuffled.groupby("stratum", sort=True)
    ]
    rng.shuffle(groups)

    selected: list[int] = []
    while len(selected) < int(n_sites):
        progressed = False
        for group in groups:
            if group:
                selected.append(group.pop())
                progressed = True
                if len(selected) == int(n_sites):
                    break
        if not progressed:
            break

    if len(selected) < int(n_sites):
        remaining = shuffled.index.difference(selected)
        selected.extend(list(remaining[: int(n_sites) - len(selected)]))

    sites = shuffled.loc[selected].copy().reset_index(drop=True)
    sites["site_id"] = [f"aus_site_{i:03d}" for i in range(1, len(sites) + 1)]
    sites["aoi_side_degrees"] = float(AOI_SIDE_DEGREES)
    sites["inland_buffer_km"] = float(INLAND_BUFFER_KM)
    return sites


def build_aoi_geometries(sites, *, aoi_side_degrees: float):
    import geopandas as gpd
    from shapely.geometry import box

    half = float(aoi_side_degrees) / 2.0
    geometries = [
        box(row.lon - half, row.lat - half, row.lon + half, row.lat + half)
        for row in sites.itertuples(index=False)
    ]
    return gpd.GeoDataFrame(sites.drop(columns="geometry"), geometry=geometries, crs="EPSG:4326")


def build_sites(
    *,
    n_sites: int = N_SITES,
    seed: int = SEED,
    aoi_side_degrees: float = AOI_SIDE_DEGREES,
    inland_buffer_km: float = INLAND_BUFFER_KM,
):
    australia = load_australia_land()
    inland = prepare_inland_polygons(australia, inland_buffer_km)
    candidates = build_candidate_pool(
        inland,
        n_candidates=max(3000, int(n_sites) * 100),
        seed=seed,
        aoi_side_degrees=aoi_side_degrees,
    )
    sites = stratified_select(candidates, n_sites=n_sites, seed=seed)
    return build_aoi_geometries(sites, aoi_side_degrees=aoi_side_degrees)


def write_geojson(gdf, path: Path) -> Path:
    gdf = gdf.copy()
    for col in gdf.columns:
        if hasattr(gdf[col], "dtype") and (
            isinstance(gdf[col].dtype, pd.StringDtype) or str(gdf[col].dtype) == "string"
        ):
            gdf[col] = gdf[col].astype(object)

    target = path
    if path.exists():
        try:
            path.unlink()
        except PermissionError:
            target = path.with_name(f"{path.stem}_{int(time.time())}{path.suffix}")
    try:
        gdf.to_file(target, driver="GeoJSON")
    except PermissionError:
        target = path.with_name(f"{path.stem}_{int(time.time())}{path.suffix}")
        gdf.to_file(target, driver="GeoJSON")
    return target


def _season_runs(result: pd.DataFrame) -> list[tuple[str, int, pd.Timestamp, pd.Timestamp]]:
    if result.empty:
        return []
    df = result.sort_values("Date").reset_index(drop=True)
    seasons = df["SeasonType"].astype(str).to_list()
    runs: list[tuple[str, int, pd.Timestamp, pd.Timestamp]] = []
    start = 0
    for i in range(1, len(seasons) + 1):
        if i == len(seasons) or seasons[i] != seasons[start]:
            runs.append(
                (
                    seasons[start],
                    i - start,
                    pd.Timestamp(df.loc[start, "Date"]),
                    pd.Timestamp(df.loc[i - 1, "Date"]),
                )
            )
            start = i
    return runs


def audit_result(
    result: pd.DataFrame,
    *,
    min_neighbor_wet_length: int = 3,
) -> dict[str, Any]:
    df = result.copy()
    df["Date"] = pd.to_datetime(df["Date"])
    runs = _season_runs(df)
    max_wet_run = max([length for label, length, _s, _e in runs if label == "Wet"] or [0])
    one_month_dry_bridges = 0
    one_month_dry_bridges_strong = 0
    for pos, (label, length, _start, _end) in enumerate(runs):
        if (
            label == "Dry"
            and length == 1
            and pos > 0
            and pos + 1 < len(runs)
            and runs[pos - 1][0] == "Wet"
            and runs[pos + 1][0] == "Wet"
        ):
            one_month_dry_bridges += 1
            if (
                runs[pos - 1][1] >= int(min_neighbor_wet_length)
                and runs[pos + 1][1] >= int(min_neighbor_wet_length)
            ):
                one_month_dry_bridges_strong += 1

    hy_counts = df.groupby("Hydro_Year").size()
    if "Hydro_Year_No_Dry_Season" in df.columns:
        no_dry_hys = df.loc[
            df["Hydro_Year_No_Dry_Season"].astype(bool),
            "Hydro_Year",
        ].nunique()
    else:
        no_dry_hys = 0
    no_dry_boundaries = (
        int(df["Hydro_Year_Boundary_Source"].astype(str).eq("no_dry_minimum").sum())
        if "Hydro_Year_Boundary_Source" in df.columns
        else 0
    )
    return {
        "max_hydro_year_months": int(hy_counts.max()) if len(hy_counts) else 0,
        "max_wet_run_months": int(max_wet_run),
        "no_dry_hydro_year_count": int(no_dry_hys),
        "no_dry_boundary_count": int(no_dry_boundaries),
        "one_month_dry_bridges": int(one_month_dry_bridges),
        "one_month_dry_bridges_strong": int(one_month_dry_bridges_strong),
        "wet_fraction": float(df["SeasonType"].eq("Wet").mean()),
        "dry_fraction": float(df["SeasonType"].eq("Dry").mean()),
        "unclassified_fraction": float(df["SeasonType"].eq("Unclassified").mean()),
    }


def summarize_site(
    row,
    artifacts: PipelineArtifacts,
    *,
    elapsed_seconds: float,
) -> dict[str, Any]:
    diag = artifacts.diagnostics
    result = artifacts.result.copy()
    audit = audit_result(
        result,
        min_neighbor_wet_length=int(diag.min_core_length_used or 3),
    )
    sources = (
        sorted(result["Data_Source"].dropna().astype(str).unique())
        if "Data_Source" in result.columns
        else []
    )
    return {
        "site_id": row.site_id,
        "country": "Australia",
        "lat_band": row.lat_band,
        "lon_band": row.lon_band,
        "lon": float(row.lon),
        "lat": float(row.lat),
        "aoi_side_degrees": float(row.aoi_side_degrees),
        "inland_buffer_km": float(row.inland_buffer_km),
        "status": "ok",
        "elapsed_seconds": float(elapsed_seconds),
        "rows_result": int(len(result)),
        "data_sources": ",".join(sources),
        "regime": diag.regime,
        "regime_source": diag.regime_source,
        "stl_strength": diag.stl_strength,
        "walsh_lawler_si": diag.walsh_lawler_si,
        "circular_R": diag.circular_R,
        "is_bimodal": diag.is_bimodal,
        "hydro_year_start_month": diag.hydro_year_start_month,
        "season_contrast_class": diag.season_contrast_class,
        "season_contrast_ratio": diag.season_contrast_ratio,
        "short_dry_gap_merged_count": diag.short_dry_gap_merged_count,
        **audit,
        "error": "",
    }


def run_site(
    row,
    *,
    output_dir: Path,
    cache_dir: Path,
    start_year: int,
    end_year: int,
    show_progress: bool,
    segmentation_method: str = "hybrid",
) -> dict[str, Any]:
    import geopandas as gpd

    site_id = str(row.site_id)
    site_dir = output_dir / site_id
    site_dir.mkdir(parents=True, exist_ok=True)

    row_dict = row._asdict()
    row_dict.pop("geometry", None)
    site_gdf = gpd.GeoDataFrame([row_dict], geometry=[row.geometry], crs="EPSG:4326")
    write_geojson(site_gdf, site_dir / f"{site_id}_aoi.geojson")

    started = time.perf_counter()
    try:
        monthly = get_monthly_aoi_rainfall(
            site_gdf,
            start_year=int(start_year),
            end_year=int(end_year),
            source="auto",
            cache_dir=cache_dir,
            show_progress=show_progress,
        )
        monthly.to_csv(site_dir / f"{site_id}_monthly_rainfall.csv", index=False)

        artifacts = classify_rainfall(
            monthly,
            segmentation_method=segmentation_method,
            raise_on_validation_error=False,
        )
        artifacts.result.to_csv(site_dir / f"{site_id}_hydroseason_result.csv", index=False)
        artifacts.fixed_monthly.to_csv(site_dir / f"{site_id}_fixed_monthly.csv")
        if artifacts.wet_boundaries is not None:
            artifacts.wet_boundaries.to_csv(
                site_dir / f"{site_id}_wet_boundaries.csv",
                index=False,
            )
        (site_dir / f"{site_id}_diagnostics.json").write_text(
            json.dumps(asdict(artifacts.diagnostics), default=str, indent=2),
            encoding="utf-8",
        )
        elapsed = time.perf_counter() - started
        return summarize_site(row, artifacts, elapsed_seconds=elapsed)
    except Exception as exc:  # noqa: BLE001 - stress harness keeps going.
        elapsed = time.perf_counter() - started
        error_text = f"{type(exc).__name__}: {exc}"
        (site_dir / f"{site_id}_error.txt").write_text(error_text, encoding="utf-8")
        return {
            "site_id": site_id,
            "country": "Australia",
            "lat_band": row.lat_band,
            "lon_band": row.lon_band,
            "lon": float(row.lon),
            "lat": float(row.lat),
            "aoi_side_degrees": float(row.aoi_side_degrees),
            "inland_buffer_km": float(row.inland_buffer_km),
            "status": "failed",
            "elapsed_seconds": float(elapsed),
            "error": error_text,
        }


def run_australia_stress(
    *,
    n_sites: int = N_SITES,
    seed: int = SEED,
    output_dir: Path = DEFAULT_OUTPUT,
    cache_dir: Path = DEFAULT_CACHE,
    start_year: int = START_YEAR,
    end_year: int = END_YEAR,
    show_progress: bool = False,
    resume: bool = True,
    segmentation_method: str = "hybrid",
) -> pd.DataFrame:
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    sites = build_sites(n_sites=n_sites, seed=seed)
    sites_csv = output_dir / "australia_silo_stress_sites.csv"
    sites.drop(columns="geometry").to_csv(sites_csv, index=False)
    write_geojson(sites, output_dir / "australia_silo_stress_sites.geojson")

    summary_path = output_dir / "australia_silo_stress_summary.csv"
    completed: set[str] = set()
    summaries: list[dict[str, Any]] = []
    if resume and summary_path.exists():
        previous = pd.read_csv(summary_path)
        ok = previous[previous["status"].eq("ok")]
        completed = set(ok["site_id"].astype(str))
        summaries.extend(previous.to_dict("records"))

    for idx, row in enumerate(sites.itertuples(index=False), start=1):
        if str(row.site_id) in completed:
            print(f"[{idx:03d}/{len(sites):03d}] {row.site_id} already ok")
            continue
        print(f"[{idx:03d}/{len(sites):03d}] {row.site_id} ({row.lat:.3f}, {row.lon:.3f})")
        summary = run_site(
            row,
            output_dir=output_dir,
            cache_dir=cache_dir,
            start_year=start_year,
            end_year=end_year,
            show_progress=show_progress,
            segmentation_method=segmentation_method,
        )
        summaries = [s for s in summaries if s.get("site_id") != row.site_id]
        summaries.append(summary)
        pd.DataFrame(summaries).sort_values("site_id").to_csv(summary_path, index=False)

    summary_df = pd.DataFrame(summaries).sort_values("site_id").reset_index(drop=True)
    summary_df.to_csv(summary_path, index=False)
    return summary_df


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n-sites", type=int, default=N_SITES)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--start-year", type=int, default=START_YEAR)
    parser.add_argument("--end-year", type=int, default=END_YEAR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--show-progress", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--segmentation-method", type=str, default="hybrid", choices=["heuristic", "cumulative_anomaly", "hybrid"])
    args = parser.parse_args(argv)

    summary = run_australia_stress(
        n_sites=args.n_sites,
        seed=args.seed,
        output_dir=args.output_dir,
        cache_dir=args.cache_dir,
        start_year=args.start_year,
        end_year=args.end_year,
        show_progress=args.show_progress,
        resume=not args.no_resume,
        segmentation_method=args.segmentation_method,
    )
    print(summary["status"].value_counts(dropna=False).to_string())
    if "regime" in summary.columns:
        print(summary["regime"].value_counts(dropna=False).to_string())
    return 0 if summary["status"].eq("ok").all() else 1


if __name__ == "__main__":
    raise SystemExit(main())
