"""Source-agnostic extent and raster loaders.

Raster support is adapted from WaterMask-TSFill commit
90983c1559e7c08951096bbf196c0daedead6b4f.  Optional geospatial imports stay
inside raster/AOI functions so extent-CSV users need only pandas and NumPy.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Literal

import numpy as np
import pandas as pd

from hydroseason._boundary import SIGNAL_FLOOR_FRACTION, robust_scale
from hydroseason._state_input import prepare_monthly_extent
from hydroseason.hydro_year import monthly_water_extent

MaskEncoding = Literal["canonical", "binary", "wofs"]


class AOIRasterizationError(RuntimeError):
    """AOI clipping or rasterization could not be applied safely."""


class GeoreferencingError(ValueError):
    """Raster lacks usable CRS or affine georeferencing."""


class IrregularGridError(GeoreferencingError):
    """Raster x/y coordinates cannot define an affine transform."""


def load_extent_csv(
    path: str | os.PathLike[str],
    *,
    date_col: str = "date",
    value_col: str = "extent_pct",
) -> pd.DataFrame:
    """Read a monthly extent CSV into date-indexed form for detection.

    This loader only parses dates and coerces the value column; it does not
    gapfill missing months or quality-screen invalid coverage. The CSV is
    valid input for ``detect_hydrological_years`` only if the upstream
    extent series already went through mask completion and quality
    screening (see the migration plan's gapfilling recommendation).
    """
    frame = pd.read_csv(path)
    missing = {date_col, value_col}.difference(frame.columns)
    if missing:
        raise ValueError(f"CSV is missing required columns: {sorted(missing)}.")
    out = frame.copy()
    out.index = pd.DatetimeIndex(pd.to_datetime(out.pop(date_col), errors="raise")).to_period("M").to_timestamp()
    out[value_col] = pd.to_numeric(out[value_col], errors="raise")
    return out.sort_index()


def load_aoi(aoi, *, to_crs: str | int | None = None):
    """Load a non-empty GeoDataFrame from vector path or GeoDataFrame."""
    try:
        import geopandas as gpd
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise ImportError("load_aoi requires the raster extra (geopandas).") from exc

    if isinstance(aoi, gpd.GeoDataFrame):
        result = aoi.copy()
    elif isinstance(aoi, (str, os.PathLike)):
        path = Path(aoi)
        if not path.exists():
            raise FileNotFoundError(f"AOI file not found: {path}")
        result = gpd.read_file(path)
    else:
        raise TypeError("aoi must be a vector path or geopandas.GeoDataFrame.")
    if result.empty:
        raise ValueError("AOI GeoDataFrame is empty.")
    result = result[~result.geometry.isna() & ~result.geometry.is_empty].copy()
    if result.empty:
        raise ValueError("AOI has no valid non-empty geometries.")
    if not result.geometry.is_valid.all():
        raise ValueError(
            "AOI contains geometrically invalid (e.g. self-intersecting) "
            "geometry; fix or repair the AOI before use."
        )
    if to_crs is not None:
        result = result.to_crs(_crs_value(to_crs))
    return result


def complete_monthly_axis(
    masks,
    start_date: str,
    end_date: str,
    *,
    invalid_value: int = -1,
    duplicate_month_policy: Literal["raise", "warn"] = "raise",
):
    """Reindex a lazy mask cube to complete monthly starts; gaps become invalid."""
    if "time" not in masks.dims:
        raise ValueError("complete_monthly_axis expects a DataArray with a 'time' dimension.")
    source = pd.DatetimeIndex(np.asarray(masks.time.values)).to_period("M").to_timestamp()
    if source.has_duplicates:
        duplicates = sorted({date.strftime("%Y-%m") for date in source[source.duplicated()]})
        if duplicate_month_policy == "raise":
            raise ValueError(f"Duplicate month timestamps: {duplicates}.")
        if duplicate_month_policy != "warn":
            raise ValueError("duplicate_month_policy must be 'raise' or 'warn'.")
        import warnings

        warnings.warn(f"Duplicate month timestamps: {duplicates}; keeping first.", UserWarning, stacklevel=2)
        masks = masks.isel(time=np.flatnonzero(~source.duplicated()))
        source = pd.DatetimeIndex(np.asarray(masks.time.values))
    start = pd.Timestamp(start_date).to_period("M").to_timestamp()
    end = pd.Timestamp(end_date).to_period("M").to_timestamp()
    axis = pd.date_range(start, end, freq="MS")
    source_set = {date.strftime("%Y-%m") for date in source}
    inserted = sorted(set(masks.attrs.get("inserted_months", [])) | ({date.strftime("%Y-%m") for date in axis} - source_set))
    out = masks.assign_coords(time=("time", source)).reindex(time=axis, fill_value=np.array(invalid_value, dtype=masks.dtype).item())
    if np.issubdtype(out.dtype, np.floating):
        out = out.fillna(np.array(invalid_value, dtype=out.dtype).item())
    out.attrs.update(masks.attrs)
    out.attrs.update({"source_months": sorted(source_set), "inserted_months": inserted, "n_inserted_timesteps": len(inserted)})
    return out


def load_monthly_masks(
    input_dir: str | os.PathLike[str],
    start_date: str,
    end_date: str,
    *,
    aoi=None,
    encoding: MaskEncoding | None = None,
    classifier: Callable | None = None,
    chunk_x: int = 512,
    chunk_y: int = 512,
    time_chunk: int = 24,
    majority: bool = True,
    duplicate_month_policy: Literal["raise", "warn"] = "raise",
):
    """Load AOI-clipped TIFF masks as lazy canonical time/y/x data.

    Explicit ``encoding`` prevents ambiguous uint8 masks from being mistaken
    for raw WOfS flags. Canonical values: dry 0, water 1, invalid -1, outside -2.
    """
    if aoi is None:
        raise ValueError("AOI is required for raster mask loading.")
    _validate_classifier(encoding, classifier)
    try:
        import rioxarray as rxr
        import xarray as xr
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise ImportError("load_monthly_masks requires the raster extra.") from exc

    files = sorted(Path(input_dir).glob("water_*.tif"))
    if not files:
        raise FileNotFoundError(f"No water_*.tif files found in {input_dir}")
    start, end = pd.Timestamp(start_date), pd.Timestamp(end_date)
    grouped: dict[pd.Timestamp, list] = {}
    for path in files:
        timestamp = _parse_date_from_name(path)
        if start <= timestamp <= end:
            arr = rxr.open_rasterio(path, chunks={"x": chunk_x, "y": chunk_y}).squeeze(drop=True)
            grouped.setdefault(timestamp.to_period("M").to_timestamp(), []).append(_classify(arr, encoding, classifier))
    if not grouped:
        raise FileNotFoundError(f"No mask files fall within {start_date} to {end_date}.")

    aoi_gdf = load_aoi(aoi)
    masks, dates, reference = [], [], None
    for month, observations in sorted(grouped.items()):
        mask = observations[0] if len(observations) == 1 else _combine_observations(xr.concat(observations, dim="time"), majority)
        mask = _clip_to_aoi(mask, aoi_gdf)
        if reference is not None:
            _assert_compatible_georef(reference, mask, context=f"month {month:%Y-%m}")
        reference = mask if reference is None else reference
        masks.append(mask)
        dates.append(month)
    return complete_monthly_axis(
        xr.concat(masks, dim="time").assign_coords(time=("time", dates)), start_date, end_date,
        duplicate_month_policy=duplicate_month_policy,
    ).chunk({"time": min(time_chunk, len(dates)), "x": chunk_x, "y": chunk_y})


def load_monthly_masks_zarr(
    zarr_path: str | os.PathLike[str], start_date: str, end_date: str, *, chunk_x: int = 512, chunk_y: int = 512,
    time_chunk: int = 24, duplicate_month_policy: Literal["raise", "warn"] = "raise",
):
    """Open an already-canonical, already-AOI-clipped Zarr mask cube lazily."""
    try:
        import xarray as xr
    except ImportError as exc:  # pragma: no cover
        raise ImportError("load_monthly_masks_zarr requires the raster extra.") from exc
    dataset = xr.open_zarr(zarr_path, chunks={"x": chunk_x, "y": chunk_y}, mask_and_scale=False)
    if "water_mask" not in dataset:
        raise ValueError("Zarr store must contain a 'water_mask' variable.")
    masks = dataset["water_mask"].sel(time=slice(pd.Timestamp(start_date), pd.Timestamp(end_date)))
    masks = complete_monthly_axis(masks, start_date, end_date, duplicate_month_policy=duplicate_month_policy)
    return masks.chunk({"time": min(time_chunk, masks.sizes["time"]), "x": chunk_x, "y": chunk_y})


def load_wofs_from_stac(
    stac_url: str, collection: str, aoi, start_date: str, end_date: str, *, crs: int | str | None = 3577,
    chunk_x: int = 512, chunk_y: int = 512, time_chunk: int = 24, majority: bool = True,
    duplicate_month_policy: Literal["raise", "warn"] = "raise", resolution: float | None = None,
):
    """Load WOfS STAC observations, compose them monthly, and clip to required AOI."""
    if aoi is None:
        raise ValueError("AOI is required for WOfS/STAC loading.")
    try:
        import xarray as xr
        import pystac_client
        import odc.stac
        import rioxarray  # noqa: F401  (registers the .rio accessor used by _clip_to_aoi)
    except ImportError as exc:  # pragma: no cover
        raise ImportError("load_wofs_from_stac requires the stac extra.") from exc
    # DEA's public S3 bucket (dea-public-data) rejects unsigned GDAL/rasterio
    # reads unless explicitly told not to sign requests; without this, every
    # lazy dask read of the returned cube fails with CPLE_AWSInvalidCredentialsError.
    os.environ.setdefault("AWS_NO_SIGN_REQUEST", "YES")
    aoi_gdf = load_aoi(aoi)
    try:
        aoi_4326 = aoi_gdf.to_crs("EPSG:4326")
        client = pystac_client.Client.open(stac_url)
        items = list(client.search(collections=[collection], datetime=f"{start_date}/{end_date}", bbox=list(aoi_4326.total_bounds)).items())
    except Exception as exc:
        raise AOIRasterizationError("STAC AOI query failed; refusing to load an unclipped raster.") from exc
    if not items:
        raise ValueError("No STAC items found for requested AOI and date range.")
    groups: dict[pd.Timestamp, list] = {}
    for item in items:
        date = pd.Timestamp(item.properties.get("datetime") or item.properties.get("start_datetime"))
        groups.setdefault(date.to_period("M").to_timestamp(), []).append(item)
    target = aoi_gdf.to_crs(_crs_value(crs)) if crs is not None else aoi_gdf
    masks, dates, reference = [], [], None
    for month, month_items in sorted(groups.items()):
        try:
            ds = odc.stac.stac_load(month_items, bands=["water"], chunks={"x": chunk_x, "y": chunk_y}, geopolygon=target.geometry, **({"crs": _crs_value(crs)} if crs is not None else {}), **({"resolution": resolution, "resampling": "mode"} if resolution is not None else {}))
            mask = _combine_observations(_classify(ds["water"], "wofs", None), majority)
            mask = _clip_to_aoi(mask, target)
        except AOIRasterizationError:
            raise
        except Exception as exc:
            raise AOIRasterizationError("AOI clip failed; refusing to process an unclipped STAC month.") from exc
        if reference is not None:
            _assert_compatible_georef(reference, mask, context=f"month {month:%Y-%m}")
        reference = mask if reference is None else reference
        masks.append(mask)
        dates.append(month)
    return complete_monthly_axis(xr.concat(masks, dim="time").assign_coords(time=("time", dates)), start_date, end_date, duplicate_month_policy=duplicate_month_policy).chunk({"time": min(time_chunk, len(dates)), "x": chunk_x, "y": chunk_y})


def plan_resolution(
    bounds_wgs84: tuple[float, float, float, float],
    target_crs: str | int,
    *,
    memory_budget_gb: float,
    observed_amplitude_pp: float | None = None,
    candidate_res_m: tuple[float, ...] = (30, 60, 100, 150, 300),
    bytes_per_scratch: float = 5.0,
    time_chunk: int = 24,
) -> tuple[float, float, float, str]:
    """Pick the finest resolution that fits a memory budget without breaking signal.

    Pure arithmetic: reprojects ``bounds_wgs84`` (WGS84/EPSG:4326 bounding box,
    as ``(minx, miny, maxx, maxy)``) into ``target_crs`` to get an AOI area in
    m^2, then estimates per-resolution peak memory and noise floor. No raster,
    file, or network I/O happens here -- callers do the real load separately
    (``load_wofs_from_stac``) once a resolution is chosen.

    Memory model: for a candidate resolution ``res`` (metres), pixel count is
    ``area_m2 / res**2``. Peak scratch bytes per pixel per timestep default to
    ``bytes_per_scratch=5``, representing the canonical int8 water mask (1
    byte) plus four boolean comparison arrays (``== water_value``, ``==
    dry_value``, ``!= outside_value``, plus one derived difference), each a
    pixel-shaped boolean/int8 array (1 byte/pixel).

    ``time_chunk`` here is a proxy for the *loaded cube's* chunk depth, not
    the reduction's peak. ``monthly_water_extent`` streams its four
    reduction accumulators (n_aoi, n_valid, n_water, n_invalid) over ``time``
    in blocks of its own ``time_block`` parameter (default 1) -- see
    ``hydroseason.hydro_year.monthly_water_extent`` -- so the reduction's
    actual peak concurrent footprint is bounded by ``time_block``, not by
    however deep the cube is chunked. What *does* still scale with
    ``time_chunk`` is ``load_wofs_from_stac``: it rechunks the dask cube it
    returns to ``{"time": min(time_chunk, len(dates)), ...}``, so a single
    chunk in the resulting dask graph genuinely spans up to ``time_chunk``
    timesteps. Even though ``monthly_water_extent`` only asks the scheduler
    for one ``time_block``-sized slice at a time, dask's scheduler operates
    on whole chunks -- depending on how tasks are fused/scheduled it can
    still materialise a full chunk's worth of data to serve a slice that
    only touches part of it. Multiplying by ``time_chunk`` therefore models
    conservative headroom for that chunk depth rather than the reduction's
    real streamed peak; it deliberately overestimates so the memory gate
    stays safe even if the scheduler doesn't fuse as favourably as
    ``time_block=1`` alone would suggest. ``peak_gb = n_pixels * time_chunk *
    bytes_per_scratch / 1e9``. Candidates are walked finest-first (ascending
    ``res_m``, since smaller pixels mean more pixels); the first (finest) one
    with ``peak_gb <= memory_budget_gb`` is the memory pick.

    Signal model: noise floor is ``100 / n_valid_at_res``, using
    ``n_valid_at_res ~= n_pixels`` (in-AOI valid fraction assumed ~1 for this
    planning estimate -- it is not an exact figure). Finer resolutions always
    have both a higher peak_gb *and* a lower (better) noise floor than coarser
    ones, so the memory pick -- the finest candidate the budget allows -- is
    already the best-signal candidate obtainable within budget; no candidate
    that costs less memory can improve on its floor. Per
    ``SIGNAL_FLOOR_FRACTION`` (from ``hydroseason._boundary``), a resolution
    is signal-safe when ``floor <= SIGNAL_FLOOR_FRACTION * observed_amplitude_pp``.

    ``reason`` values:
    - ``"ok"``: the memory pick is the finest candidate (no coarsening was
      needed to fit the budget), or no ``observed_amplitude_pp`` was supplied
      so the signal bound isn't checked.
    - ``"coarsened"``: the memory pick is coarser than the finest candidate
      (the budget forced coarsening) but still clears the signal bound --
      memory requested coarsening and signal allowed it.
    - ``"signal_veto_no_fit"``: an ``observed_amplitude_pp`` was supplied and
      the memory pick's noise floor violates the signal bound. No finer
      candidate can be substituted without exceeding the memory budget (finer
      always costs more), so no candidate satisfies both constraints.
    - ``"native_no_fit"``: even the coarsest candidate exceeds
      ``memory_budget_gb`` -- the budget is too tight for any candidate, so
      the catchment should be excluded from pattern claims.
    """
    try:
        import pyproj
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise ImportError("plan_resolution requires the raster extra (pyproj).") from exc

    minx, miny, maxx, maxy = bounds_wgs84
    transformer = pyproj.Transformer.from_crs("EPSG:4326", _crs_value(target_crs), always_xy=True)
    xs, ys = transformer.transform([minx, maxx, minx, maxx], [miny, miny, maxy, maxy])
    area_m2 = (max(xs) - min(xs)) * (max(ys) - min(ys))

    finest_res_m = min(candidate_res_m)
    ordered = sorted(candidate_res_m)

    def peak_gb_at(res_m: float) -> float:
        n_pixels = area_m2 / res_m**2
        return n_pixels * time_chunk * bytes_per_scratch / 1e9

    def floor_pp_at(res_m: float) -> float:
        n_pixels = area_m2 / res_m**2
        return 100.0 / n_pixels

    memory_pick = next((res_m for res_m in ordered if peak_gb_at(res_m) <= memory_budget_gb), None)
    if memory_pick is None:
        coarsest = ordered[-1]
        return coarsest, peak_gb_at(coarsest), floor_pp_at(coarsest), "native_no_fit"

    peak_gb = peak_gb_at(memory_pick)
    floor_pp = floor_pp_at(memory_pick)

    if observed_amplitude_pp is None:
        reason = "ok" if memory_pick == finest_res_m else "coarsened"
        return memory_pick, peak_gb, floor_pp, reason

    signal_bound = SIGNAL_FLOOR_FRACTION * observed_amplitude_pp
    if floor_pp > signal_bound:
        return memory_pick, peak_gb, floor_pp, "signal_veto_no_fit"

    reason = "ok" if memory_pick == finest_res_m else "coarsened"
    return memory_pick, peak_gb, floor_pp, reason


# Default candidate ladder mirrored from ``plan_resolution`` -- kept as a
# separate literal (rather than a shared import-time default) so a caller can
# pass a custom ``candidate_res_m`` to ``plan_resolution`` without silently
# changing what "one step coarser" means here.
_DEFAULT_CANDIDATE_RES_M: tuple[float, ...] = (30, 60, 100, 150, 300)

# Guard fires when the coarser pass retains less than this fraction of the
# probe pass's mean water fraction. 0.70 (retain >=70%) is chosen so that
# ordinary resampling noise -- a few percent drift from mode-resampling
# aggregation -- never trips the guard, while a real thin-channel collapse
# (braided/anabranching rivers where channels are only 1-2 pixels wide at the
# probe resolution and vanish entirely one step coarser) reliably does: losing
# a channel that carries a material share of total wetted area typically more
# than halves the observed fraction, well past a 30% drop. The threshold is a
# documented judgement call (not derived from a dataset), deliberately loose
# enough to avoid false positives on ordinary resampling variance.
_DEFAULT_RETENTION_THRESHOLD = 0.70


def _next_coarser_res_m(
    probe_res_m: float, guard_step_m: float | None, candidate_res_m: tuple[float, ...],
) -> float:
    """Resolve the "one step coarser" resolution used for the guard pass.

    If ``guard_step_m`` is given explicitly, it is used as-is (an absolute
    resolution in metres, not a multiplier) -- this lets a caller override the
    default ladder-based lookup entirely. Otherwise, "one step coarser" is
    defined relative to ``candidate_res_m`` (the same ladder
    ``plan_resolution`` walks): the smallest candidate strictly greater than
    ``probe_res_m``. If ``probe_res_m`` is at or beyond the coarsest candidate
    (or the ladder has no coarser entry), fall back to doubling
    ``probe_res_m`` -- a simple, well-understood step that still probes
    meaningfully coarser sampling without depending on the ladder's contents.
    """
    if guard_step_m is not None:
        return guard_step_m
    coarser_candidates = sorted(res for res in candidate_res_m if res > probe_res_m)
    return coarser_candidates[0] if coarser_candidates else probe_res_m * 2.0


def _mean_water_fraction(prepared: pd.DataFrame) -> float:
    """Mean observed water fraction over usable months.

    Takes the output of ``prepare_monthly_extent`` -- the exact same
    quality-screened frame fed to ``_boundary.robust_scale`` -- so the guard's
    fraction comparison and the amplitude estimate agree on which months
    count as usable. ``extent_pct`` is already ``100 * n_water / n_valid``
    restricted to usable rows, so dividing by 100 gives the mean water
    fraction on the same basis ``robust_scale`` uses for amplitude.
    """
    usable = prepared.loc[prepared["candidate_usable"], "extent_pct"]
    if not len(usable):
        return 0.0
    return float(usable.mean()) / 100.0


def probe_amplitude(
    stac_url: str, collection: str, aoi, start_date: str, end_date: str, *,
    crs: int | str | None = 3577, probe_res_m: float = 300, guard_step_m: float | None = None,
    candidate_res_m: tuple[float, ...] = _DEFAULT_CANDIDATE_RES_M,
    retention_threshold: float = _DEFAULT_RETENTION_THRESHOLD,
) -> dict:
    """Cheaply probe seasonal amplitude and guard against thin-channel loss when coarsening.

    Loads WOfS twice via ``load_wofs_from_stac``: once at ``probe_res_m``, once
    at one step coarser (see ``_next_coarser_res_m``) -- both coarse relative
    to any native-resolution run, so this is ~100x cheaper than a full
    fine-resolution load. This is a *probe*, not the real load: callers still
    do the real ``load_wofs_from_stac`` at whatever resolution ``plan_resolution``
    ultimately picks.

    Amplitude pipeline (matches ``_boundary.robust_scale``'s definition exactly,
    so the signal gate in ``plan_resolution`` and this detector agree): the
    probe-resolution mask goes through ``monthly_water_extent`` (raw pixel
    counts) -> ``prepare_monthly_extent`` (quality screening, produces
    ``candidate_usable`` + ``extent_pct``) -> ``robust_scale`` (10th-90th
    percentile spread of ``extent_pct`` among usable rows). Only the first
    (``probe_res_m``) pass feeds ``amplitude_pp``; the coarser pass exists
    solely to drive the guard below.

    Thin-channel guard: mean water fraction (mean ``extent_pct / 100`` over
    usable months -- see ``_mean_water_fraction``) is compared between the two
    passes. If the coarser pass retains less than ``retention_threshold``
    (default 0.70, i.e. a drop of more than 30%) of the probe pass's fraction,
    braided/thin channels that are sub-pixel at the coarser resolution are the
    most likely explanation (a real reduction in wetted area, rather than
    measurement noise, would not typically collapse this fast from one step
    on a resolution ladder). The guard then sets ``guard_caveat`` to a
    human-readable string describing the collapse (for reports, not just
    logs) and pins ``refuse_coarsen_past`` to ``probe_res_m`` -- meaning
    callers should never coarsen past this resolution for this AOI. If
    retention holds, both are ``None``.

    Returns a dict:
    - ``amplitude_pp``: seasonal amplitude estimate (percentage points) at
      ``probe_res_m``, from ``robust_scale``.
    - ``water_fraction_by_res``: ``{probe_res_m: fraction, coarser_res_m:
      fraction}`` mean water fraction at each probed resolution, so
      callers/reports can see both data points behind the guard decision.
    - ``guard_caveat``: ``None``, or a labelled human-readable string
      describing the thin-channel collapse.
    - ``refuse_coarsen_past``: ``None``, or ``probe_res_m`` if the guard fired.
    """
    coarser_res_m = _next_coarser_res_m(probe_res_m, guard_step_m, candidate_res_m)

    probe_mask = load_wofs_from_stac(
        stac_url, collection, aoi, start_date, end_date, crs=crs, resolution=probe_res_m,
    )
    probe_prepared = prepare_monthly_extent(monthly_water_extent(probe_mask))
    amplitude_pp, _noise_pp = robust_scale(probe_prepared)
    probe_fraction = _mean_water_fraction(probe_prepared)

    coarser_mask = load_wofs_from_stac(
        stac_url, collection, aoi, start_date, end_date, crs=crs, resolution=coarser_res_m,
    )
    coarser_prepared = prepare_monthly_extent(monthly_water_extent(coarser_mask))
    coarser_fraction = _mean_water_fraction(coarser_prepared)

    water_fraction_by_res = {probe_res_m: probe_fraction, coarser_res_m: coarser_fraction}

    retention = (coarser_fraction / probe_fraction) if probe_fraction > 0 else 1.0
    if probe_fraction > 0 and retention < retention_threshold:
        guard_caveat = (
            f"Thin-channel guard: mean water fraction dropped from "
            f"{probe_fraction:.4f} at {probe_res_m:.0f} m to {coarser_fraction:.4f} at "
            f"{coarser_res_m:.0f} m (retained {retention:.0%}, below the "
            f"{retention_threshold:.0%} threshold). Coarsening past {probe_res_m:.0f} m "
            f"risks losing sub-pixel/thin channels; refusing to coarsen beyond it."
        )
        refuse_coarsen_past = probe_res_m
    else:
        guard_caveat = None
        refuse_coarsen_past = None

    return {
        "amplitude_pp": amplitude_pp,
        "water_fraction_by_res": water_fraction_by_res,
        "guard_caveat": guard_caveat,
        "refuse_coarsen_past": refuse_coarsen_past,
    }


def _validate_classifier(encoding, classifier):
    if classifier is not None and not callable(classifier):
        raise TypeError("classifier must be callable.")
    if classifier is None and encoding not in {"canonical", "binary", "wofs"}:
        raise ValueError("Specify encoding='canonical', 'binary', or 'wofs', or provide classifier=callable.")
    if classifier is not None and encoding is not None:
        raise ValueError("Pass either encoding or classifier, not both.")


def _classify(arr, encoding, classifier):
    import xarray as xr

    if classifier is not None:
        result = classifier(arr)
        if not hasattr(result, "dims"):
            raise TypeError("classifier must return an xarray.DataArray.")
        in_domain = result.isin([-2, -1, 0, 1])
        canonical = xr.where(in_domain, result, np.int8(-1)).astype(np.int8)
        return _preserve_georef(canonical, arr)
    if encoding == "canonical":
        in_domain = arr.isin([-2, -1, 0, 1])
        canonical = xr.where(in_domain, arr, np.int8(-1)).astype(np.int8)
        return _preserve_georef(canonical, arr)
    if encoding == "binary":
        return _preserve_georef(xr.where(arr == 1, np.int8(1), xr.where(arr == 0, np.int8(0), np.int8(-1))).astype(np.int8), arr)
    raw = arr.fillna(1).astype(np.uint16)
    invalid = ((raw & np.uint16(1)) != 0) | arr.isnull()
    return _preserve_georef(xr.where(invalid, np.int8(-1), xr.where(arr == 128, np.int8(1), xr.where(arr == 0, np.int8(0), np.int8(-1)))).astype(np.int8), arr)


def _preserve_georef(result, source):
    """Restore rioxarray metadata dropped by xarray classification operations."""
    try:
        result = result.rio.set_spatial_dims(x_dim="x", y_dim="y")
        crs = source.rio.crs
        if crs is not None:
            result = result.rio.write_crs(crs)
        return result.rio.write_transform(source.rio.transform())
    except Exception:
        return result


def _combine_observations(series, majority):
    water, dry, invalid = (series == 1).sum("time"), (series == 0).sum("time"), (series == -1).sum("time")
    water_wins = (water > 0) & ((water > dry) if majority else True)
    import xarray as xr

    combined = xr.where(water_wins, np.int8(1), xr.where(dry > 0, np.int8(0), xr.where(invalid > 0, np.int8(-1), np.int8(-2)))).astype(np.int8)
    return _preserve_georef(combined, series)


def _clip_to_aoi(mask, aoi_gdf):
    outside_value = np.int8(-2)
    try:
        mask = mask.rio.set_spatial_dims(x_dim="x", y_dim="y")
        crs = _resolve_raster_crs(mask)
        if crs is None:
            raise GeoreferencingError("raster is missing CRS")
        # Canonical values are already int8, so an unset nodata makes
        # rio.clip's outside-AOI fill land on NaN, which casts straight to
        # 0 (dry) instead of a real sentinel. Write nodata=-2 first so
        # clip's fill value is representable and outside pixels survive as
        # outside (-2), not dry.
        mask = mask.rio.write_nodata(outside_value)
        clipped = mask.rio.clip(aoi_gdf.to_crs(crs).geometry, drop=False, all_touched=True)
    except Exception as exc:
        raise AOIRasterizationError("AOI clip failed; refusing to process an unclipped raster.") from exc
    clipped = clipped.fillna(outside_value).astype(np.int8)
    return mark_in_aoi_nodata_as_invalid(clipped, aoi_gdf)


def mark_in_aoi_nodata_as_invalid(mask, aoi, *, outside_value: int = -2, invalid_value: int = -1):
    aoi_gdf = load_aoi(aoi)
    crs = _resolve_raster_crs(mask)
    if crs is None:
        raise AOIRasterizationError("AOI masking failed: raster is missing CRS.")
    try:
        inside = _inside_aoi_mask_like(mask, aoi_gdf.to_crs(crs))
    except Exception as exc:
        if isinstance(exc, AOIRasterizationError):
            raise
        raise AOIRasterizationError("AOI masking failed; refusing unclipped raster.") from exc
    return mask.where(~((mask == outside_value) & inside), np.int8(invalid_value)).astype(np.int8)


def _inside_aoi_mask_like(template, aoi_gdf):
    try:
        from rasterio.features import geometry_mask
        import xarray as xr

        transform = _resolve_raster_transform(template)
        inside = geometry_mask(list(aoi_gdf.geometry), out_shape=(template.sizes["y"], template.sizes["x"]), transform=transform, invert=True, all_touched=True)
        return xr.DataArray(inside, dims=("y", "x"), coords={"y": template.y, "x": template.x})
    except Exception as exc:
        raise AOIRasterizationError("AOI rasterization failed; refusing unclipped raster.") from exc


def _resolve_raster_crs(da):
    try:
        return da.rio.crs
    except Exception:
        return None


def _resolve_raster_transform(da):
    try:
        transform = da.rio.transform()
    except Exception:
        transform = None
    return _spatial_transform_from_xy(da) if transform is None or _is_identity_transform(transform) else transform


def _spatial_transform_from_xy(da):
    from affine import Affine

    x, y = np.asarray(da.x.values, dtype=float), np.asarray(da.y.values, dtype=float)
    if len(x) < 2 or len(y) < 2:
        raise GeoreferencingError("x/y axes need at least two coordinates.")
    dx, dy = np.diff(x), np.diff(y)
    if not np.allclose(dx, dx[0]) or not np.allclose(dy, dy[0]):
        raise IrregularGridError("x/y coordinate spacing is irregular.")
    return Affine(dx[0], 0, x[0] - dx[0] / 2, 0, dy[0], y[0] - dy[0] / 2)


def _is_identity_transform(transform):
    from affine import Affine

    return tuple(transform)[:6] == tuple(Affine.identity())[:6]


def _assert_compatible_georef(reference, other, *, context):
    try:
        same = _resolve_raster_crs(reference) == _resolve_raster_crs(other) and _resolve_raster_transform(reference) == _resolve_raster_transform(other) and reference.sizes["x"] == other.sizes["x"] and reference.sizes["y"] == other.sizes["y"]
    except Exception as exc:
        raise GeoreferencingError(f"{context}: cannot validate georeferencing.") from exc
    if not same:
        raise GeoreferencingError(f"{context}: raster georeferencing mismatch.")


def _parse_date_from_name(path: Path) -> pd.Timestamp:
    parts = path.stem.split("_")
    if len(parts) < 4:
        raise ValueError(f"Unexpected filename format: {path.name}")
    return pd.Timestamp(f"{parts[-3]}-{parts[-2]}-{parts[-1]}")


def _crs_value(crs):
    return f"EPSG:{crs}" if isinstance(crs, int) else crs


__all__ = ["load_aoi", "load_extent_csv", "complete_monthly_axis", "load_monthly_masks", "load_monthly_masks_zarr", "load_wofs_from_stac", "plan_resolution", "probe_amplitude"]
