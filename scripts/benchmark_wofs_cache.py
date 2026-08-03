"""Run opt-in real-data WOfS cache regression and performance benchmarks.

The parent process coordinates isolated child runs so every cold measurement
starts with its own application cache directory. It writes JSON before
returning a nonzero status for either a correctness/containment gate failure
or a deterministic execution error; performance measurements never set a
failure status. See ``--help`` for the public entry point.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

os.environ.pop("PROJ_LIB", None)
os.environ.pop("PROJ_DATA", None)


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

STAC_URL = "https://explorer.dea.ga.gov.au/stac"
COLLECTION = "ga_ls_wo_3"
YEAR_START = "2015-01-01"
YEAR_END = "2015-12-31"
CRS = "EPSG:3577"
RESOLUTION = 30.0
TILE_PIXELS = 1024
CASES = {
    "gilbert": REPO_ROOT / "data" / "Gilbert_river_buffer.geojson",
    "fitzroy": REPO_ROOT / "data" / "fitzroy_kimberley_aoi.geojson",
}
BENCHMARK_MODES = ("full_aoi", "planning_only", "historical_mask")


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", dir=path.parent, delete=False
    ) as temporary:
        json.dump(payload, temporary, indent=2, sort_keys=True)
        temporary.write("\n")
        temporary_path = Path(temporary.name)
    os.replace(temporary_path, path)


def _peak_rss_bytes() -> int | None:
    try:
        import psutil

        memory = psutil.Process().memory_info()
        if hasattr(memory, "peak_wset"):
            return int(memory.peak_wset)
    except ImportError:
        pass
    try:
        import resource

        peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return peak if sys.platform == "darwin" else peak * 1024
    except ImportError:
        return None


def _directory_bytes(path: Path) -> int:
    return sum(entry.stat().st_size for entry in path.rglob("*") if entry.is_file())


def _package_versions() -> dict[str, str]:
    versions = {"python": sys.version.split()[0], "platform": platform.platform()}
    for package in ("hydroseason", "dask", "odc-stac", "pystac-client", "rioxarray", "xarray", "zarr"):
        try:
            versions[package] = version(package)
        except PackageNotFoundError:
            continue
    return versions


def _diagnostic_sum(diagnostics: list[dict[str, Any]], key: str) -> float:
    return float(sum(float(item.get(key, 0)) for item in diagnostics))


def _counts_from_primary_mask(mask) -> pd.DataFrame:
    values = np.asarray(mask.values)
    return pd.DataFrame(
        {"n_water": (values == 1).sum(axis=(1, 2), dtype=np.int64)},
        index=pd.DatetimeIndex(mask.time.values),
    )


def _expected_grid_coordinates(transform: tuple[float, ...], shape: tuple[int, int]):
    """Return pixel-centre coordinates for an unrotated affine grid."""
    a, b, c, d, e, f = transform
    if b != 0 or d != 0:
        raise ValueError("containment audit does not support rotated grids")
    height, width = shape
    return (
        c + a * (np.arange(width, dtype=float) + 0.5),
        f + e * (np.arange(height, dtype=float) + 0.5),
    )


def _audit_grid(raster, *, spatial_ndim: int) -> dict[str, Any]:
    """Extract values and complete spatial identity for a containment audit."""
    if isinstance(raster, dict):
        grid = raster
    elif hasattr(raster, "mask"):
        values = np.asarray(raster.mask, dtype=bool)
        shape = tuple(int(value) for value in raster.shape)
        x, y = _expected_grid_coordinates(tuple(raster.transform), shape)
        grid = {
            "values": values,
            "crs": str(raster.crs),
            "transform": tuple(float(value) for value in raster.transform),
            "resolution": tuple(float(value) for value in raster.resolution),
            "x": x,
            "y": y,
        }
    else:
        import rioxarray  # noqa: F401 - register the xarray ``rio`` accessor.

        values = np.asarray(raster.values)
        try:
            crs = raster.rio.crs
            transform = tuple(float(value) for value in tuple(raster.rio.transform())[:6])
            resolution = tuple(abs(float(value)) for value in raster.rio.resolution())
            x = np.asarray(raster.coords["x"].values, dtype=float)
            y = np.asarray(raster.coords["y"].values, dtype=float)
        except (AttributeError, KeyError) as exc:
            raise ValueError(
                "containment audit requires CRS, affine transform, resolution, and x/y coordinates"
            ) from exc
        grid = {
            "values": values,
            "crs": str(crs),
            "transform": transform,
            "resolution": resolution,
            "x": x,
            "y": y,
        }

    values = np.asarray(grid["values"])
    if values.ndim != spatial_ndim:
        expected = "time,y,x cube" if spatial_ndim == 3 else "y,x mask"
        raise ValueError(f"containment audit requires a {expected}")
    if str(grid.get("crs", "")) in {"", "None"}:
        raise ValueError("containment audit requires a CRS")
    if len(grid.get("transform", ())) != 6:
        raise ValueError("containment audit requires a six-coefficient affine transform")
    if len(grid.get("resolution", ())) != 2:
        raise ValueError("containment audit requires a two-axis resolution")
    if len(np.asarray(grid.get("x", ()))) != values.shape[-1] or len(
        np.asarray(grid.get("y", ()))
    ) != values.shape[-2]:
        raise ValueError("containment audit requires x/y coordinates for every spatial cell")
    return grid


def _write_audit_grid(path: Path, raster, *, spatial_ndim: int) -> None:
    """Persist audit values together with their full grid identity."""
    grid = _audit_grid(raster, spatial_ndim=spatial_ndim)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        path,
        values=np.asarray(grid["values"]),
        crs=np.asarray(grid["crs"]),
        transform=np.asarray(grid["transform"], dtype=float),
        resolution=np.asarray(grid["resolution"], dtype=float),
        x=np.asarray(grid["x"], dtype=float),
        y=np.asarray(grid["y"], dtype=float),
    )


def _read_audit_grid(path: Path) -> dict[str, Any]:
    with np.load(path, allow_pickle=False) as archive:
        return {
            "values": archive["values"],
            "crs": str(archive["crs"].item()),
            "transform": tuple(float(value) for value in archive["transform"]),
            "resolution": tuple(float(value) for value in archive["resolution"]),
            "x": archive["x"],
            "y": archive["y"],
        }


def _child_run(args: argparse.Namespace) -> int:
    """Run one bounded scientific comparison without applying a speed gate."""
    from hydroseason.io import (
        acquire_wofs_cache,
        build_planning_footprint_from_historical_mask,
        load_or_build_historical_water_mask,
        open_completed_extent_counts,
        open_completed_mask_cache,
    )

    diagnostics: list[dict[str, Any]] = []
    started = time.perf_counter()
    statistics_prepare_seconds = 0.0
    historical_water_mask = None
    planning_footprint = None
    if args.mode in ("planning_only", "historical_mask"):
        statistics_started = time.perf_counter()
        historical_water_mask = load_or_build_historical_water_mask(
            CASES[args.case],
            analysis_end=YEAR_END,
            cache_root=args.historical_mask_cache,
            offline=args.run_kind == "warm",
            crs=CRS,
            resolution=RESOLUTION,
        )
        planning_footprint = build_planning_footprint_from_historical_mask(
            historical_water_mask
        )
        statistics_prepare_seconds = time.perf_counter() - statistics_started

    common = {
        "cache_root": args.cache_root,
        "crs": CRS,
        "resolution": RESOLUTION,
        "force": args.run_kind != "warm",
        "chunk_x": TILE_PIXELS,
        "chunk_y": TILE_PIXELS,
        "compute_batch_size": args.compute_batch_size,
        "read_workers": args.read_workers if getattr(args, "read_workers", 0) > 0 else None,
        "resampling_policy": getattr(args, "resampling_policy", "categorical_safe"),
        "diagnostics_callback": diagnostics.append,
        "historical_water_mask": (
            historical_water_mask if args.mode == "historical_mask" else None
        ),
        "planning_footprint": planning_footprint,
    }
    handle = acquire_wofs_cache(
        STAC_URL,
        COLLECTION,
        CASES[args.case],
        YEAR_START,
        YEAR_END,
        offline=args.run_kind == "warm",
        **common,
    )
    frame = open_completed_extent_counts(handle, YEAR_START, YEAR_END)
    primary_mask = None
    if frame is None or args.primary_mask is not None:
        primary_mask = open_completed_mask_cache(handle, YEAR_START, YEAR_END)
    if frame is None:
        frame = _counts_from_primary_mask(primary_mask)
    if args.primary_mask is not None:
        assert primary_mask is not None
        _write_audit_grid(Path(args.primary_mask), primary_mask, spatial_ndim=3)
    if args.historical_mask is not None:
        if historical_water_mask is None:
            raise ValueError("only historical_mask runs can emit a historical mask")
        _write_audit_grid(
            Path(args.historical_mask), historical_water_mask, spatial_ndim=2
        )

    Path(args.frame).parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(
        args.frame,
        index=True,
        index_label="date",
        date_format="%Y-%m-%d",
        lineterminator="\n",
        float_format="%.17g",
    )
    frame.to_pickle(args.frame_pickle)

    payload = {
        "case": args.case,
        "mode": args.mode,
        "total_seconds": time.perf_counter() - started,
        "compute_batch_size": getattr(args, "compute_batch_size", 16),
        "read_workers": getattr(args, "read_workers", 0),
        "statistics_prepare_seconds": statistics_prepare_seconds + _diagnostic_sum(
            diagnostics, "statistics_prepare_seconds"
        ),
        "stac_read_seconds": _diagnostic_sum(diagnostics, "stac_read_seconds"),
        "active_window_count": int(_diagnostic_sum(diagnostics, "active_window_count")),
        "planned_native_pixels": int(_diagnostic_sum(diagnostics, "planned_native_pixels")),
        "loaded_pixels": int(_diagnostic_sum(diagnostics, "loaded_pixels")),
        "local_reduction_seconds": _diagnostic_sum(diagnostics, "local_reduction_seconds"),
        "peak_rss_bytes": _peak_rss_bytes(),
        "cache_bytes": _directory_bytes(Path(args.cache_root))
        + _directory_bytes(Path(args.historical_mask_cache)),
        "n_water": [int(value) for value in frame["n_water"].tolist()],
        "diagnostics": diagnostics,
        "package_versions": _package_versions(),
    }
    _write_json_atomic(Path(args.result), payload)
    return 0


def _run_child(
    args: argparse.Namespace,
    *,
    case: str,
    mode: str,
    run_kind: str,
    label: str,
    cache_root: Path,
    historical_mask_cache: Path,
    primary_mask_path: Path | None = None,
    historical_mask_path: Path | None = None,
) -> dict[str, Any]:
    # This is the authoritative per-run timing boundary: it starts before the
    # child process and stops only after its final result artifact is persisted
    # and read back.  Child-side timing cannot include persistence of the JSON
    # that carries its own timing value.
    started = time.perf_counter()
    run_dir = Path(args.work_dir) / label
    run_dir.mkdir(parents=True, exist_ok=False)
    result_path = run_dir / "result.json"
    frame_path = run_dir / "extent.csv"
    frame_pickle_path = run_dir / "extent.pkl"
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--child",
        "--case",
        case,
        "--mode",
        mode,
        "--run-kind",
        run_kind,
        "--cache-root",
        str(cache_root),
        "--historical-mask-cache",
        str(historical_mask_cache),
        "--frame",
        str(frame_path),
        "--frame-pickle",
        str(frame_pickle_path),
        "--result",
        str(result_path),
        "--compute-batch-size",
        str(getattr(args, "compute_batch_size", 16)),
        "--read-workers",
        str(getattr(args, "read_workers", 0)),
        "--resampling-policy",
        getattr(args, "resampling_policy", "categorical_safe"),
    ]
    if primary_mask_path is not None:
        command.extend(["--primary-mask", str(primary_mask_path)])
    if historical_mask_path is not None:
        command.extend(["--historical-mask", str(historical_mask_path)])
    environment = os.environ.copy()
    environment.pop("PROJ_LIB", None)
    environment.pop("PROJ_DATA", None)
    completed = subprocess.run(command, cwd=REPO_ROOT, text=True, capture_output=True, env=environment)
    if completed.returncode != 0:
        raise RuntimeError(
            f"{case} {mode} child failed ({completed.returncode}):\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    payload["total_seconds"] = time.perf_counter() - started
    payload["frame_path"] = str(frame_path)
    return payload


def _frame_from_run(run: dict[str, Any]) -> pd.DataFrame:
    return pd.read_pickle(Path(run["frame_path"]).with_suffix(".pkl"))


def _assert_exact(reference: dict[str, Any], candidate: dict[str, Any]) -> bool:
    try:
        pd.testing.assert_series_equal(
            _frame_from_run(reference)["n_water"],
            _frame_from_run(candidate)["n_water"],
            check_exact=True,
        )
    except AssertionError:
        return False
    return True


def _containment_mismatch_count(primary_masks, historical_mask) -> int:
    """Count bounded full-AOI primary-water pixels outside the exact mask.

    This deliberately exists only in the benchmark harness. Production reads
    rely on the exact mask to prune work, so a full-AOI scan there would both
    duplicate I/O and defeat the performance comparison being measured.
    """
    primary_grid = _audit_grid(primary_masks, spatial_ndim=3)
    historical_grid = _audit_grid(historical_mask, spatial_ndim=2)
    primary_values = np.asarray(primary_grid["values"])
    historical_values = np.asarray(historical_grid["values"], dtype=bool)
    if tuple(primary_values.shape[1:]) != tuple(historical_values.shape):
        raise ValueError("containment audit requires the same spatial shape")
    if primary_grid["crs"] != historical_grid["crs"]:
        raise ValueError("containment audit requires the same CRS")
    if not np.allclose(primary_grid["transform"], historical_grid["transform"]):
        raise ValueError("containment audit requires the same affine transform")
    if not np.allclose(primary_grid["resolution"], historical_grid["resolution"]):
        raise ValueError("containment audit requires the same resolution")
    if not np.allclose(primary_grid["x"], historical_grid["x"]) or not np.allclose(
        primary_grid["y"], historical_grid["y"]
    ):
        raise ValueError("containment audit requires the same x/y coordinates")
    return int(np.count_nonzero((primary_values == 1) & ~historical_values[None, :, :]))


def _median(runs: list[dict[str, Any]]) -> float:
    return float(statistics.median(run["total_seconds"] for run in runs))


def _run_benchmark(args: argparse.Namespace) -> int:
    work_dir = Path(args.work_dir)
    work_dir.mkdir(parents=True, exist_ok=False)
    case_results: dict[str, dict[str, Any]] = {}
    all_correct = True
    selected_cases = list(args.cases)
    try:
        for case in selected_cases:
            modes: dict[str, dict[str, Any]] = {}
            cold_runs: dict[str, list[dict[str, Any]]] = {}
            warm_runs: dict[str, list[dict[str, Any]]] = {}
            for mode in BENCHMARK_MODES:
                cold_runs[mode] = []
                for run_index in range(args.runs):
                    cache_root = work_dir / f"{case}-{mode}-cold-cache-{run_index}"
                    historical_cache = work_dir / f"{case}-{mode}-historical-cache-{run_index}"
                    primary_path = work_dir / f"{case}-{mode}-primary-{run_index}.npz"
                    historical_path = work_dir / f"{case}-{mode}-historical-{run_index}.npz"
                    cold_runs[mode].append(_run_child(
                        args,
                        case=case,
                        mode=mode,
                        run_kind="cold",
                        label=f"{case}-{mode}-cold-{run_index}",
                        cache_root=cache_root,
                        historical_mask_cache=historical_cache,
                        primary_mask_path=primary_path if mode == "full_aoi" else None,
                        historical_mask_path=historical_path if mode == "historical_mask" else None,
                    ))
                seed_cache = work_dir / f"{case}-{mode}-cold-cache-0"
                seed_historical_cache = work_dir / f"{case}-{mode}-historical-cache-0"
                warm_runs[mode] = [
                    _run_child(
                        args,
                        case=case,
                        mode=mode,
                        run_kind="warm",
                        label=f"{case}-{mode}-warm-{run_index}",
                        cache_root=seed_cache,
                        historical_mask_cache=seed_historical_cache,
                    )
                    for run_index in range(args.runs)
                ]
                modes[mode] = {
                    "cold_runs": cold_runs[mode],
                    "warm_runs": warm_runs[mode],
                    "cold_median_seconds": _median(cold_runs[mode]),
                    "warm_median_seconds": _median(warm_runs[mode]),
                }

            exactness = {
                mode: all(
                    _assert_exact(reference, candidate)
                    for reference, candidate in zip(
                        cold_runs["full_aoi"], cold_runs[mode], strict=True
                    )
                )
                for mode in ("planning_only", "historical_mask")
            }
            containment_mismatches = [
                _containment_mismatch_count(
                    _read_audit_grid(work_dir / f"{case}-full_aoi-primary-{run_index}.npz"),
                    _read_audit_grid(work_dir / f"{case}-historical_mask-historical-{run_index}.npz"),
                )
                for run_index in range(args.runs)
            ]
            mismatch_count = sum(containment_mismatches)
            correct = all(exactness.values()) and mismatch_count == 0
            all_correct = all_correct and correct
            case_results[case] = {
                "modes": modes,
                "exact_n_water": exactness,
                "containment_mismatch_count": mismatch_count,
                "correct": correct,
            }

        result = {
            "cases": case_results,
            "selected_cases": selected_cases,
            "correct": all_correct,
            "package_versions": _package_versions(),
        }
        _write_json_atomic(Path(args.output), result)
        return 0 if all_correct else 3
    except Exception as exc:
        _write_json_atomic(Path(args.output), {"error": repr(exc), "package_versions": _package_versions()})
        return 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "output" / "wofs_cache_benchmark.json")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument(
        "--cases",
        type=lambda value: [item.strip() for item in value.split(",") if item.strip()],
        default=["gilbert", "fitzroy"],
        help="comma-separated bounded benchmark cases (default: gilbert,fitzroy)",
    )
    parser.add_argument("--compute-batch-size", type=int, default=16)
    parser.add_argument("--read-workers", type=int, default=0)
    parser.add_argument("--resampling-policy", choices=("categorical_safe", "native_aligned"), default="categorical_safe")
    parser.add_argument("--work-dir", type=Path, default=None)
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--case", choices=sorted(CASES), help=argparse.SUPPRESS)
    parser.add_argument("--mode", choices=BENCHMARK_MODES, help=argparse.SUPPRESS)
    parser.add_argument("--run-kind", choices=("cold", "warm"), default="cold", help=argparse.SUPPRESS)
    parser.add_argument("--cache-root", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--historical-mask-cache", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--frame", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--frame-pickle", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--result", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--primary-mask", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--historical-mask", type=Path, help=argparse.SUPPRESS)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.runs < 1:
        raise SystemExit("--runs must be at least 1")
    unknown = sorted(set(args.cases) - set(CASES))
    if not args.cases or unknown:
        raise SystemExit(f"--cases must name supported cases: {', '.join(sorted(CASES))}")
    if args.child:
        required = (
            args.case,
            args.mode,
            args.cache_root,
            args.historical_mask_cache,
            args.frame,
            args.frame_pickle,
            args.result,
        )
        if any(value is None for value in required):
            raise SystemExit(
                "child mode requires case, mode, cache roots, frame, and result paths"
            )
        return _child_run(args)
    if args.work_dir is None:
        args.work_dir = args.output.parent / f".wofs-cache-benchmark-{time.time_ns()}"
    return _run_benchmark(args)


if __name__ == "__main__":
    raise SystemExit(main())
