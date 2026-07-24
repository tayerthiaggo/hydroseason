"""Run opt-in real-data WOfS cache regression and performance benchmarks.

The parent process coordinates isolated child runs so every cold measurement
starts with its own application cache directory. It writes JSON even when a
performance or exactness gate fails; see ``--help`` for the public entry point.
"""

from __future__ import annotations

import argparse
import hashlib
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

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

STAC_URL = "https://explorer.dea.ga.gov.au/stac"
COLLECTION = "ga_ls_wo_3"
YEAR_START = "2015-01-01"
YEAR_END = "2015-12-31"
RESOLUTION = 30.0
TILE_PIXELS = 1024
LEGACY_QUERIES_PER_RUN = 2
CASES = {
    "gilbert": REPO_ROOT / "data" / "Gilbert_river_buffer.geojson",
    "fitzroy": REPO_ROOT / "data" / "fitzroy_kimberley_aoi.geojson",
}
GDAL_SETTINGS = {
    "inherited": {},
    "vsi_cache_false": {"VSI_CACHE": "FALSE"},
    "vsi_cache_true_8mb": {"VSI_CACHE": "TRUE", "VSI_CACHE_SIZE": "8388608"},
}


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", dir=path.parent, delete=False
    ) as temporary:
        json.dump(payload, temporary, indent=2, sort_keys=True)
        temporary.write("\n")
        temporary_path = Path(temporary.name)
    os.replace(temporary_path, path)


def _frame_bytes(frame: pd.DataFrame) -> bytes:
    ordered = frame.loc[:, sorted(frame.columns)].sort_index()
    return ordered.to_csv(
        index=True,
        index_label="date",
        date_format="%Y-%m-%d",
        lineterminator="\n",
        float_format="%.17g",
    ).encode("utf-8")


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


def _child_run(args: argparse.Namespace) -> int:
    from hydroseason.io import load_wofs_monthly_extent

    diagnostics: list[dict[str, int]] = []
    started = time.perf_counter()
    common = {
        "cache_dir": args.extent_cache,
        "crs": 3577,
        "resolution": RESOLUTION,
        "force": True,
        "tile_pixels": TILE_PIXELS,
        "precompute_wet_aoi": True,
        "auto_tiling": False,
    }
    if args.mode == "legacy":
        import hydroseason._io_geo as geo

        real_query = geo._query_wofs_items

        def counted_query(*query_args, **query_kwargs):
            diagnostics.append({"query_count": 1})
            return real_query(*query_args, **query_kwargs)

        geo._query_wofs_items = counted_query
        frame = load_wofs_monthly_extent(
            STAC_URL, COLLECTION, CASES[args.case], YEAR_START, YEAR_END, **common
        )
    else:
        frame = load_wofs_monthly_extent(
            STAC_URL,
            COLLECTION,
            CASES[args.case],
            YEAR_START,
            YEAR_END,
            mask_cache_dir=args.mask_cache,
            offline=args.mode == "warm",
            diagnostics_callback=diagnostics.append,
            **common,
        )
    seconds = time.perf_counter() - started
    payload = {
        "case": args.case,
        "mode": args.mode,
        "seconds": seconds,
        "output_digest": hashlib.sha256(_frame_bytes(frame)).hexdigest(),
        "peak_rss_bytes": _peak_rss_bytes(),
        "cache_bytes": _directory_bytes(Path(args.mask_cache)) if args.mask_cache else 0,
        "diagnostics": diagnostics,
        "package_versions": _package_versions(),
    }
    frame.to_csv(
        args.frame,
        index=True,
        index_label="date",
        date_format="%Y-%m-%d",
        lineterminator="\n",
        float_format="%.17g",
    )
    frame.to_pickle(args.frame_pickle)
    _write_json_atomic(Path(args.result), payload)
    return 0


def _run_child(
    args: argparse.Namespace,
    *,
    case: str,
    mode: str,
    label: str,
    setting: dict[str, str],
    mask_cache: Path | None,
) -> dict[str, Any]:
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
        "--extent-cache",
        str(run_dir / "extent_cache"),
        "--frame",
        str(frame_path),
        "--frame-pickle",
        str(frame_pickle_path),
        "--result",
        str(result_path),
    ]
    if mask_cache is not None:
        command.extend(["--mask-cache", str(mask_cache)])
    environment = os.environ.copy()
    environment.update(setting)
    completed = subprocess.run(command, cwd=REPO_ROOT, text=True, capture_output=True, env=environment)
    if completed.returncode != 0:
        raise RuntimeError(
            f"{case} {mode} child failed ({completed.returncode}):\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    payload["frame_path"] = str(frame_path)
    return payload


def _frame_from_run(run: dict[str, Any]) -> pd.DataFrame:
    return pd.read_pickle(Path(run["frame_path"]).with_suffix(".pkl"))


def _assert_exact(reference: dict[str, Any], candidate: dict[str, Any]) -> bool:
    if reference["output_digest"] != candidate["output_digest"]:
        return False
    try:
        pd.testing.assert_frame_equal(_frame_from_run(reference), _frame_from_run(candidate), check_exact=True)
    except AssertionError:
        return False
    return True


def _median(runs: list[dict[str, Any]]) -> float:
    return float(statistics.median(run["seconds"] for run in runs))


def _diagnostic_total(runs: list[dict[str, Any]], key: str) -> int:
    return sum(int(item.get(key, 0)) for run in runs for item in run["diagnostics"])


def _rss_not_over(reference: list[dict[str, Any]], candidate: list[dict[str, Any]], ratio: float) -> bool:
    reference_values = [run["peak_rss_bytes"] for run in reference if run["peak_rss_bytes"] is not None]
    candidate_values = [run["peak_rss_bytes"] for run in candidate if run["peak_rss_bytes"] is not None]
    if not reference_values or not candidate_values:
        return True
    return statistics.median(candidate_values) <= statistics.median(reference_values) * ratio


def _summarise_case(
    legacy: list[dict[str, Any]], cold: list[dict[str, Any]], warm: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    legacy_median = _median(legacy)
    cold_median = _median(cold)
    cold_improvement = (legacy_median - cold_median) / legacy_median
    result = {
        "legacy_runs": legacy,
        "cache_cold_runs": cold,
        "legacy_median_seconds": legacy_median,
        "cold_median_seconds": cold_median,
        "cold_median_improvement": cold_improvement,
        "cold_median_regression": -cold_improvement,
        "cold_hard_gate": cold_improvement >= 0.20,
        "cold_target_met": cold_improvement >= 0.35,
        "cold_stretch_met": cold_improvement >= 0.40,
        "legacy_stac_calls": _diagnostic_total(legacy, "query_count"),
        "cold_stac_calls": _diagnostic_total(cold, "query_count"),
        "cold_graph_builds": _diagnostic_total(cold, "graph_count"),
        "cold_task_count": _diagnostic_total(cold, "task_count"),
        "cold_chunks_considered": _diagnostic_total(cold, "chunks_considered"),
        "cold_chunks_written": _diagnostic_total(cold, "chunks_written"),
    }
    if warm is not None:
        warm_median = _median(warm)
        result.update(
            {
                "cache_warm_runs": warm,
                "cached_median_seconds": warm_median,
                "cached_median_improvement": (legacy_median - warm_median) / legacy_median,
                "cached_stac_calls": _diagnostic_total(warm, "query_count"),
                "cached_graph_builds": _diagnostic_total(warm, "graph_count"),
            }
        )
    return result


def _source_counts_ok(result: dict[str, Any], *, runs: int) -> bool:
    """Hard source-count gate for the real one-year benchmark cases."""
    return (
        result["gilbert"]["legacy_stac_calls"] == LEGACY_QUERIES_PER_RUN * runs
        and result["fitzroy"]["legacy_stac_calls"] == LEGACY_QUERIES_PER_RUN * runs
        and result["gilbert"]["cold_stac_calls"] == runs
        and result["fitzroy"]["cold_stac_calls"] == runs
        and result["gilbert"]["cold_graph_builds"] == runs
        and result["fitzroy"]["cold_graph_builds"] == runs
        and result["gilbert"]["cached_stac_calls"] == 0
        and result["gilbert"]["cached_graph_builds"] == 0
    )


def _run_benchmark(args: argparse.Namespace) -> int:
    work_dir = Path(args.work_dir)
    work_dir.mkdir(parents=True, exist_ok=False)
    gdal_results: dict[str, dict[str, Any]] = {}
    all_exact = True
    try:
        for setting_name, setting in GDAL_SETTINGS.items():
            per_case: dict[str, Any] = {}
            for case in CASES:
                legacy = []
                cold = []
                for run_index in range(args.runs):
                    legacy.append(_run_child(
                        args, case=case, mode="legacy",
                        label=f"{setting_name}-{case}-legacy-{run_index}", setting=setting, mask_cache=None,
                    ))
                    cold_cache = work_dir / f"{setting_name}-{case}-cold-cache-{run_index}"
                    cold.append(_run_child(
                        args, case=case, mode="cold",
                        label=f"{setting_name}-{case}-cold-{run_index}", setting=setting, mask_cache=cold_cache,
                    ))
                exact = all(_assert_exact(left, right) for left, right in zip(legacy, cold, strict=True))
                all_exact = all_exact and exact
                summary = _summarise_case(legacy, cold, None)
                summary["exact_output_equality"] = exact
                per_case[case] = summary
            gdal_results[setting_name] = per_case

        promoted = "inherited"
        inherited = gdal_results["inherited"]
        for setting_name in ("vsi_cache_false", "vsi_cache_true_8mb"):
            candidate = gdal_results[setting_name]
            faster_both = all(
                candidate[case]["cold_median_seconds"] <= inherited[case]["cold_median_seconds"] * 0.95
                for case in CASES
            )
            exact_both = all(
                candidate[case]["exact_output_equality"]
                and all(
                    _assert_exact(reference, contender)
                    for reference, contender in zip(
                        inherited[case]["cache_cold_runs"],
                        candidate[case]["cache_cold_runs"],
                        strict=True,
                    )
                )
                for case in CASES
            )
            rss_ok = all(
                _rss_not_over(
                    inherited[case]["cache_cold_runs"], candidate[case]["cache_cold_runs"], 1.10
                )
                for case in CASES
            )
            if faster_both and exact_both and rss_ok:
                promoted = setting_name
                break

        selected = gdal_results[promoted]
        warm_cache = work_dir / f"gilbert-warm-cache-{promoted}"
        _run_child(
            args, case="gilbert", mode="cold", label=f"gilbert-warm-seed-{promoted}",
            setting=GDAL_SETTINGS[promoted], mask_cache=warm_cache,
        )
        warm = [
            _run_child(
                args,
                case="gilbert",
                mode="warm",
                label=f"gilbert-warm-{promoted}-{run_index}",
                setting=GDAL_SETTINGS[promoted],
                mask_cache=warm_cache,
            )
            for run_index in range(args.runs)
        ]
        selected["gilbert"] = _summarise_case(
            selected["gilbert"]["legacy_runs"], selected["gilbert"]["cache_cold_runs"], warm
        ) | {"exact_output_equality": selected["gilbert"]["exact_output_equality"]}
        all_exact = all_exact and all(
            _assert_exact(reference, candidate)
            for reference, candidate in zip(selected["gilbert"]["legacy_runs"], warm, strict=True)
        )

        result = {
            "gilbert": selected["gilbert"],
            "fitzroy": selected["fitzroy"],
            "gdal_ab": gdal_results,
            "gdal_promoted_setting": promoted,
            "exact_output_equality": all_exact,
            "package_versions": _package_versions(),
        }
        _write_json_atomic(Path(args.output), result)

        source_failure = not all_exact or not _source_counts_ok(result, runs=args.runs)
        hard_failure = (
            result["gilbert"]["cold_median_improvement"] < 0.20
            or result["fitzroy"]["cold_median_regression"] > 0.10
            or result["gilbert"]["cached_median_improvement"] < 0.80
        )
        if source_failure:
            return 3
        return 2 if hard_failure else 0
    except Exception as exc:
        _write_json_atomic(Path(args.output), {"error": repr(exc), "package_versions": _package_versions()})
        return 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "output" / "wofs_cache_benchmark.json")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--work-dir", type=Path, default=None)
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--case", choices=sorted(CASES), help=argparse.SUPPRESS)
    parser.add_argument("--mode", choices=("legacy", "cold", "warm"), help=argparse.SUPPRESS)
    parser.add_argument("--mask-cache", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--extent-cache", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--frame", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--frame-pickle", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--result", type=Path, help=argparse.SUPPRESS)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.runs < 1:
        raise SystemExit("--runs must be at least 1")
    if args.child:
        required = (args.case, args.mode, args.extent_cache, args.frame, args.frame_pickle, args.result)
        if any(value is None for value in required):
            raise SystemExit("child mode requires case, mode, extent cache, frame, and result paths")
        return _child_run(args)
    if args.work_dir is None:
        args.work_dir = args.output.parent / f".wofs-cache-benchmark-{time.time_ns()}"
    return _run_benchmark(args)


if __name__ == "__main__":
    raise SystemExit(main())
