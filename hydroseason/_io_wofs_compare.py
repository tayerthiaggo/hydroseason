"""Categorical comparison of WOfS spatial matrices."""

from __future__ import annotations

import xarray as xr

from hydroseason._io_geo import _assert_compatible_georef


def count_categorical_mismatches(baseline: xr.DataArray, test: xr.DataArray) -> tuple[int, int]:
    """Compare two canonical categorical arrays of identical shape and georeferencing.

    Returns:
        (total_test_valid, mismatched_categorical_pixels)
        where "valid" means within the shared domain (value != -2).
    """
    _assert_compatible_georef(baseline, test, context="count_categorical_mismatches")

    # Domain is the intersection of non-outside pixels
    domain_mask = (baseline != -2) & (test != -2)
    
    total_valid = int(domain_mask.sum().item())
    mismatches = int(((baseline != test) & domain_mask).sum().item())
    
    return total_valid, mismatches
