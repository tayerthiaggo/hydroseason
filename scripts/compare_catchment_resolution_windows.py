"""Compare native-pixel and coarsened WOfS signal on lower-reach windows.

This is a real-data, network-backed empirical check, not a CI test. It answers:
"how much does monthly water-extent signal change if we load WOfS at native
30 m versus a coarsened resolution?"

For each catchment fixture in ``data/catchments``:

1. load its boundary and AHGF stream reaches;
2. infer a lower/outlet reach from ``nextdownid`` + largest upstream area;
3. take the downstream endpoint of that reach;
4. build a 50 km square centred on that point;
5. clip that square to the catchment boundary;
6. run the same monthly-extent pipeline at native and coarsened resolution;
7. export per-month CSVs, AOI GeoJSONs, JSON/CSV summaries, and a visual HTML report.

Run:

    python scripts/compare_catchment_resolution_windows.py
    python scripts/compare_catchment_resolution_windows.py --only gilbert_river_qld,moonie_river_qld_nsw
    python scripts/compare_catchment_resolution_windows.py --coarse-resolution 100 --side-km 50

Requires ``hydroseason[stac]`` and network access to DEA STAC.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd

os.environ.pop("PROJ_LIB", None)
os.environ.pop("PROJ_DATA", None)
os.environ.setdefault("AWS_NO_SIGN_REQUEST", "YES")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from hydroseason._boundary import robust_scale  # noqa: E402
from hydroseason._state_input import prepare_monthly_extent  # noqa: E402
from hydroseason.io import load_wofs_monthly_extent  # noqa: E402

STAC_URL = "https://explorer.dea.ga.gov.au/stac"
COLLECTION = "ga_ls_wo_3"
OUTPUT_CRS = 3577  # GDA94 / Australian Albers
DEFAULT_START_DATE = "2005-01-01"
DEFAULT_END_DATE = "2025-12-31"
DEFAULT_NATIVE_RES_M = 30.0
DEFAULT_COARSE_RES_M = 100.0
DEFAULT_TIME_BLOCK = 12

CATCHMENTS_DIR = REPO_ROOT / "data" / "catchments"
OUTPUT_DIR = REPO_ROOT / "output" / "resolution_window_comparison"
REPORT_PATH = REPO_ROOT / "notebooks" / "hydroseason_resolution_window_comparison.html"

PLOTLY_CDN = "https://cdn.plot.ly/plotly-2.35.2.min.js"


@dataclass(frozen=True)
class CatchmentSpec:
    key: str
    display_name: str
    river: str
    region: str


CATCHMENTS = [
    CatchmentSpec("gilbert_river_qld", "Gilbert River (QLD)", "Gilbert River", "QLD"),
    CatchmentSpec("fitzroy_river_wa", "Fitzroy River (WA)", "Fitzroy River", "WA Kimberley"),
    CatchmentSpec("moonie_river_qld_nsw", "Moonie River (QLD/NSW)", "Moonie River", "QLD/NSW"),
    CatchmentSpec("lachlan_river_nsw", "Lachlan River (NSW)", "Lachlan River", "NSW"),
    CatchmentSpec("paroo_river_qld_nsw", "Paroo River (QLD/NSW)", "Paroo River", "QLD/NSW"),
    CatchmentSpec("daly_river_nt", "Daly River (NT)", "Daly River", "NT"),
]


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
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise ImportError("compare_catchment_resolution_windows.py requires geopandas.") from exc
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
    """Pick lower/outlet reach: major outlet with largest upstream area.

    AHGF carries ``hydroid`` and ``nextdownid``. For a catchment subset, an
    outlet reach normally has ``nextdownid`` outside the catchment's hydroid
    set. If that signal is missing, fall back to largest ``upstrdarea``.
    """
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
    output_crs: int | str = OUTPUT_CRS,
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


def _read_catchment_inputs(key: str):
    gpd = _import_geopandas()
    boundary_path = CATCHMENTS_DIR / f"{key}_boundary.parquet"
    streams_path = CATCHMENTS_DIR / f"{key}_streams.parquet"
    if not boundary_path.exists():
        raise FileNotFoundError(f"Missing boundary fixture: {boundary_path}")
    if not streams_path.exists():
        raise FileNotFoundError(f"Missing streams fixture: {streams_path}")
    return gpd.read_parquet(boundary_path), gpd.read_parquet(streams_path)


def _safe_float(value) -> float | None:
    if pd.isna(value):
        return None
    return float(value)


def _robust_signal(prepared: pd.DataFrame) -> tuple[float, float]:
    if "candidate_usable" not in prepared:
        prepared = prepared.copy()
        prepared["candidate_usable"] = True
    amplitude_pp, noise_pp = robust_scale(prepared)
    return float(amplitude_pp), float(noise_pp)


def compare_prepared_extent_series(
    native: pd.DataFrame,
    coarse: pd.DataFrame,
    *,
    native_res_m: float,
    coarse_res_m: float,
) -> dict:
    """Quantify month-by-month agreement between prepared extent series."""
    native_s = native["extent_pct"].rename("native")
    coarse_s = coarse["extent_pct"].rename("coarse")
    aligned = native_s.to_frame().join(coarse_s.to_frame(), how="inner")

    native_usable = native.get("candidate_usable", pd.Series(True, index=native.index))
    coarse_usable = coarse.get("candidate_usable", pd.Series(True, index=coarse.index))
    usable = native_usable.rename("native_usable").to_frame().join(
        coarse_usable.rename("coarse_usable").to_frame(), how="inner"
    )
    aligned = aligned.join(usable, how="inner")
    aligned = aligned[aligned["native_usable"] & aligned["coarse_usable"]]
    aligned = aligned[["native", "coarse"]].dropna()

    abs_diff = (aligned["native"] - aligned["coarse"]).abs()
    correlation = float(aligned["native"].corr(aligned["coarse"])) if len(aligned) >= 2 else None

    native_wet_month = aligned["native"].idxmax() if len(aligned) else None
    coarse_wet_month = aligned["coarse"].idxmax() if len(aligned) else None
    native_dry_month = aligned["native"].idxmin() if len(aligned) else None
    coarse_dry_month = aligned["coarse"].idxmin() if len(aligned) else None

    native_amp, native_noise = _robust_signal(native)
    coarse_amp, coarse_noise = _robust_signal(coarse)

    return {
        "native_res_m": float(native_res_m),
        "coarse_res_m": float(coarse_res_m),
        "n_months_compared": int(len(aligned)),
        "native_amplitude_pp": native_amp,
        "coarse_amplitude_pp": coarse_amp,
        "amplitude_delta_pp": coarse_amp - native_amp,
        "native_noise_pp": native_noise,
        "coarse_noise_pp": coarse_noise,
        "noise_delta_pp": coarse_noise - native_noise,
        "correlation": correlation,
        "max_abs_diff_extent_pct": _safe_float(abs_diff.max()) if len(abs_diff) else None,
        "mean_abs_diff_extent_pct": _safe_float(abs_diff.mean()) if len(abs_diff) else None,
        "native_wet_month": native_wet_month.strftime("%Y-%m-%d") if native_wet_month is not None else None,
        "coarse_wet_month": coarse_wet_month.strftime("%Y-%m-%d") if coarse_wet_month is not None else None,
        "native_dry_month": native_dry_month.strftime("%Y-%m-%d") if native_dry_month is not None else None,
        "coarse_dry_month": coarse_dry_month.strftime("%Y-%m-%d") if coarse_dry_month is not None else None,
        "same_wet_month": native_wet_month == coarse_wet_month,
        "same_dry_month": native_dry_month == coarse_dry_month,
    }


def _series_records(native: pd.DataFrame, coarse: pd.DataFrame) -> list[dict]:
    aligned = native["extent_pct"].rename("native").to_frame().join(
        coarse["extent_pct"].rename("coarse").to_frame(), how="outer"
    )
    records = []
    for ts, row in aligned.iterrows():
        records.append(
            {
                "date": pd.Timestamp(ts).strftime("%Y-%m-%d"),
                "native": _safe_float(row["native"]),
                "coarse": _safe_float(row["coarse"]),
                "abs_diff": _safe_float(abs(row["native"] - row["coarse"]))
                if pd.notna(row["native"]) and pd.notna(row["coarse"])
                else None,
            }
        )
    return records


def _run_extent_pipeline(
    aoi,
    start_date: str,
    end_date: str,
    resolution_m: float,
    *,
    time_block: int = DEFAULT_TIME_BLOCK,
    cache_dir: Path | None = None,
    force: bool = False,
) -> dict:
    print(f"    load/cache WOfS extent at {resolution_m:.0f} m", flush=True)
    started = time.perf_counter()
    extent = load_wofs_monthly_extent(
        STAC_URL,
        COLLECTION,
        aoi,
        start_date,
        end_date,
        crs=OUTPUT_CRS,
        resolution=resolution_m,
        time_block=time_block,
        cache_dir=cache_dir,
        force=force,
    )
    print(
        f"    extent ready in {time.perf_counter() - started:.1f}s; {len(extent)} months",
        flush=True,
    )
    prepared = prepare_monthly_extent(extent)
    amplitude_pp, noise_pp = _robust_signal(prepared)
    return {
        "extent": extent,
        "prepared": prepared,
        "amplitude_pp": amplitude_pp,
        "noise_pp": noise_pp,
    }


def _write_extent_csv(path: Path, extent: pd.DataFrame, prepared: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = extent.copy()
    for col in ("candidate_usable", "quality_flag"):
        if col in prepared.columns and col not in out.columns:
            out[col] = prepared[col]
    out.to_csv(path, index_label="date")


def run_one_catchment(
    spec: CatchmentSpec,
    *,
    side_km: float,
    start_date: str,
    end_date: str,
    native_res_m: float,
    coarse_res_m: float,
    time_block: int,
    output_dir: Path,
    force: bool = False,
) -> dict:
    catchment_dir = output_dir / spec.key
    result_path = catchment_dir / "comparison.json"
    boundary_source = CATCHMENTS_DIR / f"{spec.key}_boundary.parquet"
    streams_source = CATCHMENTS_DIR / f"{spec.key}_streams.parquet"
    expected_config = {
        "date_range": [start_date, end_date],
        "side_km": side_km,
        "native_resolution_m": native_res_m,
        "coarse_resolution_m": coarse_res_m,
        "time_block": time_block,
        "boundary_sha256": hashlib.sha256(boundary_source.read_bytes()).hexdigest(),
        "streams_sha256": hashlib.sha256(streams_source.read_bytes()).hexdigest(),
    }
    if result_path.exists() and not force:
        try:
            cached_result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cached_result = None
        if cached_result is not None and cached_result.get("run_config") == expected_config:
            print(f"[{spec.key}] checkpoint found, skipping -- use --force to redo", flush=True)
            return cached_result
        print(f"[{spec.key}] checkpoint stale for current settings; rebuilding", flush=True)

    catchment_dir.mkdir(parents=True, exist_ok=True)
    print(f"[{spec.key}] lower-reach 50 km window", flush=True)
    boundary, streams = _read_catchment_inputs(spec.key)
    window = build_lower_reach_window(spec.key, boundary, streams, side_km=side_km, output_crs=OUTPUT_CRS)

    window.square_aoi.to_crs(4326).to_file(catchment_dir / "lower_reach_square_50km.geojson", driver="GeoJSON")
    window.analysis_aoi.to_crs(4326).to_file(
        catchment_dir / "lower_reach_square_50km_clipped_to_catchment.geojson",
        driver="GeoJSON",
    )

    print(
        f"[{spec.key}] lower_hydroid={window.lower_hydroid} "
        f"bbox={tuple(round(v, 5) for v in window.analysis_bounds_wgs84)}",
        flush=True,
    )

    native = _run_extent_pipeline(
        window.analysis_aoi, start_date, end_date, native_res_m, time_block=time_block,
        cache_dir=catchment_dir / "extent_cache" / "native", force=force,
    )
    coarse = _run_extent_pipeline(
        window.analysis_aoi, start_date, end_date, coarse_res_m, time_block=time_block,
        cache_dir=catchment_dir / "extent_cache" / "coarse", force=force,
    )

    _write_extent_csv(catchment_dir / f"extent_{native_res_m:.0f}m.csv", native["extent"], native["prepared"])
    _write_extent_csv(catchment_dir / f"extent_{coarse_res_m:.0f}m.csv", coarse["extent"], coarse["prepared"])

    comparison = compare_prepared_extent_series(
        native["prepared"], coarse["prepared"],
        native_res_m=native_res_m,
        coarse_res_m=coarse_res_m,
    )

    result = {
        "catchment_key": spec.key,
        "display_name": spec.display_name,
        "river": spec.river,
        "region": spec.region,
        "date_range": [start_date, end_date],
        "lower_hydroid": window.lower_hydroid,
        "side_km": side_km,
        "square_bounds_projected": list(window.square_bounds_projected),
        "analysis_bounds_wgs84": list(window.analysis_bounds_wgs84),
        "comparison": comparison,
        "series": _series_records(native["prepared"], coarse["prepared"]),
        "run_config": expected_config,
        "artifacts": {
            "aoi_square_geojson": str(catchment_dir / "lower_reach_square_50km.geojson"),
            "aoi_analysis_geojson": str(catchment_dir / "lower_reach_square_50km_clipped_to_catchment.geojson"),
            "native_extent_csv": str(catchment_dir / f"extent_{native_res_m:.0f}m.csv"),
            "coarse_extent_csv": str(catchment_dir / f"extent_{coarse_res_m:.0f}m.csv"),
        },
    }
    temporary_result_path = result_path.with_suffix(".json.tmp")
    temporary_result_path.write_text(
        json.dumps(result, indent=2, default=str), encoding="utf-8"
    )
    os.replace(temporary_result_path, result_path)
    return result


def _json_num(value, default="null"):
    if value is None or pd.isna(value):
        return default
    return json.dumps(round(float(value), 6))


def _format_metric(value, spec: str, suffix: str = "") -> str:
    if value is None or pd.isna(value):
        return "N/A"
    return f"{format(float(value), spec)}{suffix}"


def _plot_div(result: dict) -> str:
    div_id = f"chart-{result['catchment_key']}"
    dates = [r["date"] for r in result["series"]]
    native = [r["native"] for r in result["series"]]
    coarse = [r["coarse"] for r in result["series"]]
    diff = [r["abs_diff"] for r in result["series"]]
    comp = result["comparison"]
    traces = [
        {
            "x": dates,
            "y": native,
            "type": "scatter",
            "mode": "lines+markers",
            "name": f"Native {comp['native_res_m']:.0f} m",
            "line": {"color": "#0284c7", "width": 2},
        },
        {
            "x": dates,
            "y": coarse,
            "type": "scatter",
            "mode": "lines+markers",
            "name": f"Coarsened {comp['coarse_res_m']:.0f} m",
            "line": {"color": "#f97316", "width": 2},
        },
        {
            "x": dates,
            "y": diff,
            "type": "bar",
            "name": "|Difference| pp",
            "marker": {"color": "rgba(100,116,139,0.30)"},
            "yaxis": "y2",
        },
    ]
    layout = {
        "title": {"text": f"{result['display_name']} lower-reach window", "font": {"size": 15}},
        "height": 370,
        "margin": {"l": 55, "r": 55, "t": 45, "b": 45},
        "xaxis": {"type": "date", "rangeslider": {"visible": True, "thickness": 0.07}},
        "yaxis": {"title": "Water extent (%)", "range": [0, 105]},
        "yaxis2": {"title": "|diff| pp", "overlaying": "y", "side": "right", "rangemode": "tozero"},
        "legend": {"orientation": "h", "y": 1.18},
        "hovermode": "x unified",
        "plot_bgcolor": "#ffffff",
        "paper_bgcolor": "#ffffff",
    }
    return (
        f'<div id="{div_id}" class="plotly-chart"></div>'
        f"<script>Plotly.newPlot({json.dumps(div_id)}, {json.dumps(traces)}, {json.dumps(layout)}, "
        f'{{responsive: true, displaylogo: false}});</script>'
    )


def build_html_report(results: list[dict], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    sections = []
    for result in results:
        comp = result["comparison"]
        rows.append(
            f"""<tr>
              <td><a href="#{html.escape(result['catchment_key'])}">{html.escape(result['display_name'])}</a></td>
              <td>{html.escape(str(result['lower_hydroid']))}</td>
              <td>{comp['native_res_m']:.0f} / {comp['coarse_res_m']:.0f}</td>
              <td>{comp['n_months_compared']}</td>
              <td>{_json_num(comp['correlation'], 'N/A')}</td>
              <td>{_json_num(comp['mean_abs_diff_extent_pct'], 'N/A')}</td>
              <td>{_json_num(comp['max_abs_diff_extent_pct'], 'N/A')}</td>
              <td>{_json_num(comp['amplitude_delta_pp'], 'N/A')}</td>
              <td>{'yes' if comp['same_wet_month'] else 'no'} / {'yes' if comp['same_dry_month'] else 'no'}</td>
            </tr>"""
        )
        sections.append(
            f"""<section class="card" id="{html.escape(result['catchment_key'])}">
              <h2>{html.escape(result['display_name'])}</h2>
              <p class="meta">Lower hydroid {html.escape(str(result['lower_hydroid']))}
              · {result['side_km']:.0f} km square, clipped to catchment
              · bbox WGS84 {', '.join(f'{v:.4f}' for v in result['analysis_bounds_wgs84'])}</p>
              <div class="kpis">
                <div><span>Amplitude Δ</span><strong>{_format_metric(comp['amplitude_delta_pp'], '+.3f', ' pp')}</strong></div>
                <div><span>Mean |diff|</span><strong>{_format_metric(comp['mean_abs_diff_extent_pct'], '.3f', ' pp')}</strong></div>
                <div><span>Max |diff|</span><strong>{_format_metric(comp['max_abs_diff_extent_pct'], '.3f', ' pp')}</strong></div>
                <div><span>Correlation</span><strong>{_format_metric(comp['correlation'], '.3f')}</strong></div>
              </div>
              {_plot_div(result)}
            </section>"""
        )

    date_ranges = {tuple(r["date_range"]) for r in results}
    date_label = ", ".join(f"{a}..{b}" for a, b in sorted(date_ranges))
    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>HydroSeason resolution-window comparison</title>
<script src="{PLOTLY_CDN}"></script>
<style>
  body {{ margin:0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background:#f8fafc; color:#334155; }}
  header {{ background:linear-gradient(135deg,#0f172a,#164e63); color:white; padding:34px; }}
  header h1 {{ margin:0 0 8px; font-size:28px; font-weight:650; }}
  header p {{ margin:0; color:#cbd5e1; }}
  main {{ max-width:1180px; margin:0 auto; padding:24px; }}
  .card {{ background:white; border:1px solid #e2e8f0; border-radius:12px; padding:20px; margin:20px 0; box-shadow:0 1px 3px rgba(15,23,42,.06); }}
  table {{ width:100%; border-collapse:collapse; }}
  th {{ text-align:left; background:#f1f5f9; color:#64748b; font-size:12px; text-transform:uppercase; letter-spacing:.04em; padding:9px 10px; }}
  td {{ border-top:1px solid #eef2f7; padding:9px 10px; font-size:14px; }}
  a {{ color:#0284c7; text-decoration:none; font-weight:600; }}
  h2 {{ color:#0f172a; margin:0 0 4px; }}
  .meta {{ margin:0 0 14px; color:#64748b; font-size:13px; }}
  .kpis {{ display:flex; gap:12px; flex-wrap:wrap; margin:14px 0; }}
  .kpis div {{ background:#f8fafc; border:1px solid #eef2f7; border-radius:10px; padding:9px 14px; min-width:130px; }}
  .kpis span {{ display:block; color:#94a3b8; font-size:11px; text-transform:uppercase; letter-spacing:.04em; }}
  .kpis strong {{ display:block; color:#0f172a; font-size:18px; }}
  .plotly-chart {{ width:100%; }}
</style>
</head>
<body>
<header>
  <h1>HydroSeason native-vs-coarsened lower-reach comparison</h1>
  <p>DEA WOfS {html.escape(date_label)} · lower stream outlet point · 50 km square clipped to each catchment</p>
</header>
<main>
  <section class="card">
    <h2>Summary</h2>
    <table>
      <thead><tr><th>Catchment</th><th>Lower hydroid</th><th>Res m</th><th>Months</th><th>Corr</th><th>Mean |diff| pp</th><th>Max |diff| pp</th><th>Amplitude Δ pp</th><th>Same wet/dry</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
  </section>
  {''.join(sections)}
</main>
</body>
</html>"""
    output_path.write_text(html_doc, encoding="utf-8")
    return output_path


def _write_summary_tables(results: list[dict], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = []
    for r in results:
        row = {
            "catchment_key": r["catchment_key"],
            "display_name": r["display_name"],
            "lower_hydroid": r["lower_hydroid"],
            "side_km": r["side_km"],
            **r["comparison"],
        }
        summary.append(row)
    pd.DataFrame(summary).to_csv(output_dir / "summary.csv", index=False)
    (output_dir / "summary.json").write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")


def _select_specs(only: str | None) -> list[CatchmentSpec]:
    if only is None:
        return CATCHMENTS
    wanted = {part.strip() for part in only.split(",") if part.strip()}
    selected = [spec for spec in CATCHMENTS if spec.key in wanted]
    missing = wanted - {spec.key for spec in selected}
    if missing:
        raise SystemExit(f"Unknown catchment key(s): {sorted(missing)}")
    return selected


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", default=None, help="comma-separated catchment keys")
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument("--end-date", default=DEFAULT_END_DATE)
    parser.add_argument("--native-resolution", type=float, default=DEFAULT_NATIVE_RES_M)
    parser.add_argument("--coarse-resolution", type=float, default=DEFAULT_COARSE_RES_M)
    parser.add_argument("--side-km", type=float, default=50.0)
    parser.add_argument(
        "--time-block",
        type=int,
        default=DEFAULT_TIME_BLOCK,
        help="months computed together inside each annual cache piece (default: 12)",
    )
    parser.add_argument("--workers", type=int, default=2, help="parallel catchments (default: 2)")
    parser.add_argument("--force", action="store_true", help="rerun catchments with existing JSON")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    return parser


def _run_catchments(specs, *, workers: int, run_kwargs: dict):
    """Run catchments concurrently and retain the configured report order."""
    ordered_results: list[dict | None] = [None] * len(specs)
    failures = []
    with ThreadPoolExecutor(
        max_workers=min(workers, len(specs)), thread_name_prefix="resolution-window"
    ) as executor:
        futures = {
            executor.submit(run_one_catchment, spec, **run_kwargs): (index, spec)
            for index, spec in enumerate(specs)
        }
        for future in as_completed(futures):
            index, spec = futures[future]
            try:
                ordered_results[index] = future.result()
            except Exception as exc:  # noqa: BLE001 - continue with other catchments
                print(f"[{spec.key}] FAILED: {exc!r}", flush=True)
                failures.append({"catchment_key": spec.key, "error": repr(exc)})
    return [result for result in ordered_results if result is not None], failures


def main(argv: Iterable[str] | None = None) -> None:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    if args.workers < 1:
        parser.error("--workers must be at least 1")
    if args.time_block < 1:
        parser.error("--time-block must be at least 1")
    specs = _select_specs(args.only)
    if not specs:
        parser.error("no catchments selected")
    run_kwargs = {
        "side_km": args.side_km,
        "start_date": args.start_date,
        "end_date": args.end_date,
        "native_res_m": args.native_resolution,
        "coarse_res_m": args.coarse_resolution,
        "time_block": args.time_block,
        "output_dir": args.output_dir,
        "force": args.force,
    }
    results, failures = _run_catchments(
        specs, workers=args.workers, run_kwargs=run_kwargs
    )

    if not results:
        raise SystemExit("No catchments produced results; nothing to report.")

    _write_summary_tables(results, args.output_dir)
    report_path = build_html_report(results, args.report_path)
    print(f"\nReport written to: {report_path.resolve()}")
    print(f"Summary written to: {(args.output_dir / 'summary.csv').resolve()}")
    if failures:
        fail_path = args.output_dir / "failures.json"
        fail_path.write_text(json.dumps(failures, indent=2), encoding="utf-8")
        print(f"Failures written to: {fail_path.resolve()}")


if __name__ == "__main__":
    main()
