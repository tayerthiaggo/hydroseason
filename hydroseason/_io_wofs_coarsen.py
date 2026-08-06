"""Exact spatial coarsening for categorical canonical WOfS values."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr
from affine import Affine

from hydroseason._io_wofs_zarr import (
    WOfSCacheHandle,
    WOfSCacheIdentity,
    WOfSCacheRequest,
    _sha256_digest,
    create_cache_handle,
)


@dataclass(frozen=True)
class DerivedCacheIdentity:
    source_identity: Any
    factor: int
    reducer_version: int = 1

    @property
    def start_date(self) -> str:
        return self.source_identity.request.start_date

    @property
    def end_date(self) -> str:
        return self.source_identity.request.end_date

    @property
    def request_digest(self) -> str:
        import dataclasses
        req = self.source_identity.request
        req_kwargs = dataclasses.asdict(req)
        req_kwargs["resolution"] = req.resolution * self.factor
        new_req = WOfSCacheRequest(**req_kwargs)
        return new_req.request_digest()

    @property
    def digest(self) -> str:
        return _sha256_digest(self.as_dict())

    def as_dict(self) -> dict[str, Any]:
        import dataclasses
        return dataclasses.asdict(self)


def validate_resolution_factor(source_resolution: float, target_resolution: float) -> int:
    """Validate target resolution is an integer multiple of source resolution."""
    factor = target_resolution / source_resolution
    if factor < 1 or not np.isclose(factor, round(factor), atol=1e-5):
        raise ValueError(
            f"Target resolution {target_resolution} must be an integer multiple "
            f"of source resolution {source_resolution}"
        )
    return int(round(factor))


def coarsen_canonical_mask(mask: xr.DataArray, factor: int) -> xr.DataArray:
    """Coarsen canonical WOfS categorical data by an integer factor.

    Categorical rules per block:
    - inside == 0 -> -2
    - water > dry -> 1
    - dry > water -> 0
    - tie or no valid -> -1

    Pads the bottom/right edges with -2 to preserve the upper-left origin.
    Updates the GeoTransform and x/y coordinates accordingly.
    """
    if factor == 1:
        return mask

    pad_y = (factor - (mask.sizes["y"] % factor)) % factor
    pad_x = (factor - (mask.sizes["x"] % factor)) % factor

    # Pad coordinates extrapolated so that coarsen doesn't error
    padded = mask
    if pad_y > 0 or pad_x > 0:
        padded = mask.pad(y=(0, pad_y), x=(0, pad_x), constant_values=-2)
        # Fix the coordinates if they were padded with NaNs
        if "x" in mask.coords and "y" in mask.coords:
            dx = float(mask.x[1] - mask.x[0]) if mask.sizes["x"] > 1 else 0.0
            dy = float(mask.y[1] - mask.y[0]) if mask.sizes["y"] > 1 else 0.0
            new_x = mask.x.values[0] + dx * np.arange(padded.sizes["x"])
            new_y = mask.y.values[0] + dy * np.arange(padded.sizes["y"])
            padded = padded.assign_coords(x=new_x, y=new_y)

    is_inside = (padded != -2)
    is_water = (padded == 1)
    is_dry = (padded == 0)

    # Use sum on boolean arrays
    inside_count = is_inside.coarsen(x=factor, y=factor, boundary="exact").sum()
    water_count = is_water.coarsen(x=factor, y=factor, boundary="exact").sum()
    dry_count = is_dry.coarsen(x=factor, y=factor, boundary="exact").sum()

    # Initialize with -1 (tie or no valid)
    out = xr.full_like(inside_count, -1, dtype=mask.dtype)
    out = out.where(dry_count <= water_count, 0)
    out = out.where(water_count <= dry_count, 1)
    out = out.where(inside_count > 0, -2)
    
    # Restore the correct type if where casted it
    out = out.astype(mask.dtype)

    # Update transform if available
    if "spatial_ref" in mask.coords:
        spatial_ref = out.coords["spatial_ref"].copy()
        transform_str = spatial_ref.attrs.get("GeoTransform")
        if transform_str:
            parts = [float(p) for p in transform_str.split(" ")]
            # Affine.from_gdal uses (c, a, b, f, d, e)
            source_transform = Affine.from_gdal(*parts)
            new_transform = source_transform * Affine.scale(factor)
            spatial_ref.attrs["GeoTransform"] = (
                f"{new_transform.c} {new_transform.a} {new_transform.b} "
                f"{new_transform.f} {new_transform.d} {new_transform.e}"
            )
            out = out.assign_coords(spatial_ref=spatial_ref)
            
            # Precisely recalculate x and y from the new transform
            # Pixel centers are half a pixel offset from the origin
            out_x = new_transform.c + new_transform.a * (np.arange(out.sizes["x"]) + 0.5)
            out_y = new_transform.f + new_transform.e * (np.arange(out.sizes["y"]) + 0.5)
            out = out.assign_coords(x=out_x, y=out_y)

    return out


def derive_resolution_cache(
    source_handle: WOfSCacheHandle,
    target_root: Path,
    *,
    factor: int,
    overwrite: bool = False,
) -> WOfSCacheHandle:
    """Materialise a derived resolution cache year-by-year from a source Zarr cache."""
    import zarr

    manifest_path = source_handle.path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    
    # Reconstruct source identity
    source_identity = WOfSCacheIdentity.from_dict(manifest["identity"])

    derived_identity = DerivedCacheIdentity(source_identity, factor)
    target_handle = create_cache_handle(target_root, derived_identity)

    source_group = zarr.open_group(source_handle.path, mode="r")
    target_group = zarr.open_group(target_handle.path, mode="a")

    for year_str in source_group.group_keys():
        if not overwrite and year_str in target_group:
            try:
                ds = xr.open_zarr(target_handle.path, group=year_str)
                ds.close()
                continue
            except Exception:
                # Corrupted group, rebuild
                shutil.rmtree(target_handle.path / year_str, ignore_errors=True)

        ds_source = xr.open_zarr(source_handle.path, group=year_str)
        
        # Apply coarsening to all DataArrays in the Dataset
        derived_vars = {}
        for var_name, da in ds_source.data_vars.items():
            if "spatial_ref" not in da.coords:
                # Try to propagate spatial_ref if available in the dataset
                if "spatial_ref" in ds_source.coords:
                    da = da.assign_coords(spatial_ref=ds_source.coords["spatial_ref"])
            
            derived_da = coarsen_canonical_mask(da, factor)
            derived_vars[var_name] = derived_da
            
        ds_derived = xr.Dataset(derived_vars)
        for var in ds_derived.variables.values():
            # Coordinates recomputed by ``coarsen(...).sum()`` are float64 in
            # memory but, when the source array came from ``xr.open_zarr``,
            # still carry the source's on-disk int64 coordinate encoding --
            # writing float data under a stale int encoding is what triggers
            # xarray's fill-value warning, for coordinates as well as data.
            var.encoding.clear()
            if np.issubdtype(var.dtype, np.integer):
                var.encoding["_FillValue"] = None
        ds_derived.to_zarr(target_handle.path, group=year_str, mode="a")

    return target_handle
