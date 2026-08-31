"""Environment probing: what is installed, and is it usable.

Two failures in the field motivated this module. First, `uv pip check`
reports every *installed* package as compatible and says nothing about
declared-but-uninstalled optional extras, so a environment missing `s3fs`,
`h5py`, and `h5netcdf` looked healthy while `fetch_rainfall=True` could
never succeed -- and only said so after the water acquisition had finished.
Second, `import netCDF4` emitted "numpy.ndarray size changed, may indicate
binary incompatibility" under an unsupported Python: a native ABI mismatch
that can take the whole interpreter down rather than raise.

Every check imports its target inside a function and converts failure into
data. This module never exits, never prints, and never raises for a missing
dependency -- rendering and policy belong to the caller
(:mod:`hydroseason.cli`'s ``doctor`` subcommand, and the upfront rainfall
warning in :mod:`hydroseason.workflow`).
"""
from __future__ import annotations

import importlib
import subprocess
import sys
from dataclasses import dataclass
from typing import Literal, Sequence

CheckStatus = Literal["ok", "warning", "error"]

# Lower bound inclusive, upper bound exclusive -- mirrors
# pyproject.toml's requires-python = ">=3.10,<3.14". Kept as data so
# tests/test_release_metadata.py can hold the two in agreement.
SUPPORTED_PYTHON: tuple[tuple[int, int], tuple[int, int]] = ((3, 10), (3, 14))

# module name -> extra that installs it.
_CORE_MODULES = {"pandas": "", "numpy": ""}
_RASTER_MODULES = {
    "xarray": "raster",
    "rioxarray": "raster",
    "rasterio": "raster",
    "geopandas": "raster",
    "shapely": "raster",
    "affine": "raster",
    "dask": "raster",
    "zarr": "raster",
    "h5netcdf": "raster",
    "h5py": "raster",
    "s3fs": "raster",
    # Connected-component labelling for the recurrent-water screen: scipy on
    # the in-memory path, dask_image on the dask path. Missing either one
    # fails a real run, so probe both rather than reporting all-green.
    "scipy": "raster",
    "dask_image": "raster",
}
_STAC_MODULES = {
    "pystac": "stac",
    "pystac_client": "stac",
    "odc.stac": "stac",
    "tqdm": "stac",
    # The batch scheduler's memory admission reads available RAM through it.
    "psutil": "stac",
}

# What get_monthly_silo_rainfall actually needs: it imports s3fs and opens
# the SILO NetCDF with engine="h5netcdf" (which needs h5py underneath).
_RAINFALL_MODULES = ("h5netcdf", "h5py", "s3fs")


@dataclass(frozen=True)
class EnvironmentCheck:
    """One probe's outcome. ``detail`` is written for a human to act on."""

    name: str
    status: CheckStatus
    detail: str


def _probe_module(name: str, extra: str) -> EnvironmentCheck:
    try:
        module = importlib.import_module(name)
    except Exception as exc:
        remedy = (
            f' -- install with: pip install "hydroseason[{extra}]"'
            if extra
            else ""
        )
        return EnvironmentCheck(
            name, "error", f"{type(exc).__name__}: {exc}{remedy}"
        )
    version = getattr(module, "__version__", "unknown version")
    return EnvironmentCheck(name, "ok", str(version))


def _probe_python() -> EnvironmentCheck:
    low, high = SUPPORTED_PYTHON
    current = sys.version_info[:2]
    text = ".".join(str(part) for part in sys.version_info[:3])
    window = (
        f">={low[0]}.{low[1]},<{high[0]}.{high[1]}"
    )
    if low <= current < high:
        return EnvironmentCheck("python", "ok", f"{text} (supported {window})")
    return EnvironmentCheck(
        "python",
        "error",
        f"{text} is outside the supported window {window}. Native raster "
        "wheels (netCDF4, rasterio, h5py) are only ABI-matched to NumPy on "
        "tested interpreters; outside this window imports can abort the "
        "process instead of raising.",
    )


def _probe_netcdf4_abi() -> EnvironmentCheck:
    """Probe netCDF4 in a child process and surface native failures.

    netCDF4 is not a hydroseason dependency (the SILO path uses h5netcdf),
    but xarray will select it for a .nc read when it is present, and a
    NumPy-ABI-mismatched build can abort the interpreter instead of raising.
    Never import it into the doctor process itself.
    """
    probe = (
        "import importlib.util, warnings\n"
        "if importlib.util.find_spec('netCDF4') is None:\n"
        "    print('not-installed')\n"
        "else:\n"
        "    warnings.simplefilter('error', RuntimeWarning)\n"
        "    import netCDF4\n"
        "    print(getattr(netCDF4, '__version__', 'installed'))\n"
    )
    try:
        completed = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return EnvironmentCheck(
            "netCDF4 ABI",
            "error",
            "netCDF4 import probe exceeded 20 seconds -- reinstall netCDF4 "
            "against the installed NumPy, or remove it.",
        )
    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()
    if completed.returncode == 0 and stdout == "not-installed":
        return EnvironmentCheck(
            "netCDF4 ABI", "ok", "netCDF4 not installed (not required)"
        )
    if completed.returncode == 0:
        return EnvironmentCheck(
            "netCDF4 ABI", "ok", f"imported in subprocess ({stdout})"
        )
    detail = stderr or stdout or f"child process exited {completed.returncode}"
    return EnvironmentCheck(
        "netCDF4 ABI",
        "error",
        f"netCDF4 import probe exited {completed.returncode}: {detail} -- "
        "reinstall netCDF4 against the installed NumPy, or remove it "
        "(hydroseason reads NetCDF via h5netcdf).",
    )


def check_environment(
    *, groups: Sequence[str] = ("core", "raster", "stac")
) -> tuple[EnvironmentCheck, ...]:
    """Probe the interpreter and the requested dependency groups."""
    checks: list[EnvironmentCheck] = []
    if "core" in groups:
        checks.append(_probe_python())
        checks.extend(
            _probe_module(name, extra) for name, extra in _CORE_MODULES.items()
        )
    if "raster" in groups:
        checks.extend(
            _probe_module(name, extra) for name, extra in _RASTER_MODULES.items()
        )
        checks.append(_probe_netcdf4_abi())
    if "stac" in groups:
        checks.extend(
            _probe_module(name, extra) for name, extra in _STAC_MODULES.items()
        )
    return tuple(checks)


def missing_rainfall_dependencies() -> tuple[str, ...]:
    """Names SILO rainfall needs but cannot import, sorted.

    Cheap enough to call before a long run: three import attempts, each of
    which is a no-op once the module is in ``sys.modules``.
    """
    missing = []
    for name in _RAINFALL_MODULES:
        try:
            importlib.import_module(name)
        except Exception:
            missing.append(name)
    return tuple(sorted(missing))


__all__ = [
    "CheckStatus",
    "EnvironmentCheck",
    "SUPPORTED_PYTHON",
    "check_environment",
    "missing_rainfall_dependencies",
]
