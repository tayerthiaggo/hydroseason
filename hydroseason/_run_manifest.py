"""Machine-readable run provenance manifests for HydroSeason analysis."""

from __future__ import annotations

import hashlib
import importlib.metadata
import platform
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

import hydroseason

from ._catchment import CatchmentAnalysis
from ._method_policy import method_policy_fingerprint, method_policy_manifest
from ._state_input import prepare_monthly_extent

REQUIRED_SECTIONS: tuple[str, ...] = (
    "schema",
    "created_at_utc",
    "hydroseason_version",
    "python",
    "dependencies",
    "method",
    "input",
    "acquisition",
    "preflight",
    "analysis",
    "random_state",
    "outputs",
)

CORE_DEPENDENCY_NAMES: tuple[str, ...] = (
    "affine",
    "dask",
    "dask-image",
    "geopandas",
    "h5netcdf",
    "h5py",
    "numcodecs",
    "numpy",
    "odc-stac",
    "pandas",
    "psutil",
    "pystac",
    "pystac-client",
    "rasterio",
    "rioxarray",
    "scipy",
    "shapely",
    "s3fs",
    "tqdm",
    "zarr",
)

_CREDENTIAL_KEY_RE = re.compile(
    r"(token|secret|password|credential|api[_-]?key|access[_-]?key|auth)",
    re.IGNORECASE,
)
_URL_USERINFO_RE = re.compile(r"://([^:]+):([^@]+)@")


def sha256_file(path: str | Path) -> str:
    """Compute SHA-256 digest of a file in streaming chunks."""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def _sanitize_provenance(val: Any) -> Any:
    """Recursively scrub credentials and sensitive fields from provenance data."""
    if isinstance(val, Mapping):
        sanitized = {}
        for k, v in val.items():
            if _CREDENTIAL_KEY_RE.search(str(k)):
                continue
            sanitized[k] = _sanitize_provenance(v)
        return sanitized
    elif isinstance(val, (list, tuple)):
        return [_sanitize_provenance(v) for v in val]
    elif isinstance(val, str):
        return _URL_USERINFO_RE.sub(r"://<redacted>:<redacted>@", val)
    return val


def _extract_date_range(extent: Any) -> tuple[str | None, str | None]:
    try:
        if isinstance(extent, (pd.DataFrame, pd.Series)):
            if "date" in getattr(extent, "columns", ()):
                dates = pd.to_datetime(extent["date"]).dropna()
            elif isinstance(extent.index, pd.DatetimeIndex):
                dates = extent.index.dropna()
            else:
                prepared = prepare_monthly_extent(extent)
                dates = prepared.index.dropna()
            if len(dates) > 0:
                return (
                    dates.min().strftime("%Y-%m-%d"),
                    dates.max().strftime("%Y-%m-%d"),
                )
    except Exception:
        pass
    return (None, None)


def _collect_dependencies() -> dict[str, str]:
    deps: dict[str, str] = {}
    for pkg in sorted(CORE_DEPENDENCY_NAMES):
        try:
            deps[pkg] = importlib.metadata.version(pkg)
        except importlib.metadata.PackageNotFoundError:
            pass
    return deps


def build_run_manifest(
    *,
    extent: Any,
    analysis: CatchmentAnalysis,
    artifacts: Mapping[str, Path],
    run_context: Mapping[str, object] | None = None,
    created_at_utc: datetime | None = None,
) -> dict[str, object]:
    """Construct a complete, machine-readable run provenance dictionary."""
    if created_at_utc is None:
        created_str = datetime.now(timezone.utc).isoformat()
    elif isinstance(created_at_utc, datetime):
        if created_at_utc.tzinfo is None:
            created_str = created_at_utc.replace(tzinfo=timezone.utc).isoformat()
        else:
            created_str = created_at_utc.isoformat()
    else:
        created_str = str(created_at_utc)

    # Dependencies
    dependencies = _collect_dependencies()

    # Method policy
    method_dict = dict(method_policy_manifest())
    method_dict["fingerprint"] = method_policy_fingerprint()

    # Input section
    date_min, date_max = _extract_date_range(extent)
    n_rows = len(extent) if hasattr(extent, "__len__") else 0
    input_section = {
        "date_max": date_max,
        "date_min": date_min,
        "extent_sha256": analysis.input_fingerprint,
        "n_rows": n_rows,
    }

    # Acquisition section
    if run_context is not None and "acquisition" in run_context:
        raw_acq = run_context["acquisition"]
        if isinstance(raw_acq, Mapping):
            acquisition = _sanitize_provenance(dict(raw_acq))
        else:
            acquisition = {"source_kind": str(raw_acq)}
    else:
        acquisition = {"source_kind": "supplied_in_memory"}

    # Preflight section
    if run_context is not None and "preflight" in run_context:
        raw_preflight = run_context["preflight"]
        if isinstance(raw_preflight, Mapping):
            preflight = _sanitize_provenance(dict(raw_preflight))
        else:
            preflight = {"value": str(raw_preflight)}
    else:
        preflight = {}

    # Analysis section
    pass2_applied = (
        int(analysis.hydro_years["trough_refinement_applied"].sum())
        if "trough_refinement_applied" in analysis.hydro_years.columns
        else 0
    )
    pass2_abstained = (
        int((analysis.hydro_years.get("trough_refinement_status") == "abstained").sum())
        if "trough_refinement_status" in analysis.hydro_years.columns
        else 0
    )
    if "trough_refinement_reason" in analysis.hydro_years.columns:
        counts = analysis.hydro_years["trough_refinement_reason"].dropna().value_counts().to_dict()
        reason_codes = {str(k): int(v) for k, v in sorted(counts.items())}
    else:
        reason_codes = {}

    if hasattr(analysis.events, "events"):
        n_events = len(analysis.events.events)
    else:
        try:
            n_events = len(analysis.events)
        except Exception:
            n_events = 0

    analysis_section = {
        "n_events": n_events,
        "n_hydro_years": len(analysis.hydro_years),
        "pass2_abstained_count": pass2_abstained,
        "pass2_applied_count": pass2_applied,
        "reason": analysis.route_reason,
        "reason_codes": reason_codes,
        "regime": analysis.regime.regime,
        "route": analysis.route,
        "warnings": list(analysis.warnings),
    }

    # Outputs section (manifest does not hash itself)
    outputs: dict[str, dict[str, Any]] = {}
    for key, path in sorted(artifacts.items()):
        p = Path(path).resolve()
        if p.exists():
            size_bytes = p.stat().st_size
            digest = sha256_file(p)
        else:
            size_bytes = 0
            digest = ""
        outputs[key] = {
            "path": str(p),
            "sha256": digest,
            "size_bytes": size_bytes,
        }

    manifest: dict[str, object] = {
        "schema": "hydroseason-run-manifest-v1",
        "created_at_utc": created_str,
        "hydroseason_version": hydroseason.__version__,
        "python": platform.python_version(),
        "dependencies": dependencies,
        "method": method_dict,
        "input": input_section,
        "acquisition": acquisition,
        "preflight": preflight,
        "analysis": analysis_section,
        "random_state": analysis.random_state,
        "outputs": outputs,
    }

    return manifest


__all__ = [
    "CORE_DEPENDENCY_NAMES",
    "REQUIRED_SECTIONS",
    "build_run_manifest",
    "sha256_file",
]
