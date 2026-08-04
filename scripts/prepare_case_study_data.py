"""Prepare and normalize reproducible case-study extent CSV inputs and manifest.

Reads raw source CSVs from output/water_extent_csv/, normalizes them to
2005-01-01 .. 2025-12-01, checks completeness across all 20 combinations (5 catchments x 4 resolutions),
and writes case_studies/data/extent/*.csv and case_studies/data/manifest.json.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = REPO_ROOT / "output" / "water_extent_csv"
CASE_DATA_DIR = REPO_ROOT / "case_studies" / "data"
EXTENT_DIR = CASE_DATA_DIR / "extent"

CATCHMENTS = [
    "daly_river_nt",
    "fitzroy_river_wa",
    "gilbert_river_qld",
    "lachlan_river_nsw",
    "moonie_river_qld_nsw",
]

RESOLUTIONS = [30, 60, 90, 300]

START_DATE = "2005-01-01"
END_DATE = "2025-12-01"

EXPORT_COLUMNS = [
    "date",
    "extent_pct",
    "invalid_pct",
    "n_water",
    "n_valid",
    "n_aoi",
]


def _get_git_commit() -> str:
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout.strip()
    except Exception:
        return "unknown"


def normalize_extent_csv(
    source: Path,
    destination: Path,
    *,
    start: str = START_DATE,
    end: str = END_DATE,
    catchment: str = "",
    resolution: int = 30,
) -> dict:
    if not source.exists():
        raise FileNotFoundError(f"Source file not found: {source}")

    raw = pd.read_csv(source)
    date_col = raw.columns[0]
    raw = raw.rename(columns={date_col: "date"})

    for col in ("extent_pct", "invalid_pct", "n_water", "n_valid", "n_aoi"):
        if col in raw.columns:
            raw[col] = pd.to_numeric(raw[col], errors="coerce")

    raw["month_start"] = pd.to_datetime(raw["date"]).dt.to_period("M").dt.to_timestamp()

    expected_dates = pd.date_range(start, end, freq="MS")

    # Filter to start .. end
    filtered = raw[
        (raw["month_start"] >= pd.Timestamp(start))
        & (raw["month_start"] <= pd.Timestamp(end))
    ].copy()

    # Check for duplicates
    dups = filtered[filtered.duplicated(subset=["month_start"], keep=False)]
    if not dups.empty:
        dup_dates = dups["month_start"].dt.strftime("%Y-%m-%d").unique().tolist()
        raise ValueError(
            f"Duplicate month(s) found in {source} for {catchment} {resolution}m: {dup_dates}"
        )

    # Check for missing months
    actual_dates = set(filtered["month_start"])
    missing_dates = set(expected_dates) - actual_dates
    if missing_dates:
        missing_fmt = sorted([d.strftime("%Y-%m-%d") for d in missing_dates])
        raise ValueError(
            f"Missing {len(missing_fmt)} expected month(s) in {source} for {catchment} {resolution}m: {missing_fmt[:5]}"
        )

    filtered = filtered.sort_values("month_start")
    filtered["date"] = filtered["month_start"].dt.strftime("%Y-%m-%d")

    # Select columns
    for col in EXPORT_COLUMNS:
        if col not in filtered.columns:
            filtered[col] = pd.NA

    out = filtered[EXPORT_COLUMNS].copy()
    out["n_water"] = out["n_water"].astype("Int64")
    out["n_valid"] = out["n_valid"].astype("Int64")
    out["n_aoi"] = out["n_aoi"].astype("Int64")

    destination.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(destination, index=False, lineterminator="\n", encoding="utf-8")

    content = destination.read_bytes()
    sha256_hash = hashlib.sha256(content).hexdigest()

    return {
        "catchment": catchment,
        "resolution_m": resolution,
        "file": f"extent/{destination.name}",
        "sha256": sha256_hash,
        "rows": len(out),
        "start": start,
        "end": end,
    }


def build_manifest(
    extent_dir: Path = EXTENT_DIR,
    output_manifest: Path = CASE_DATA_DIR / "manifest.json",
    generator_commit: str | None = None,
) -> dict:
    commit = generator_commit or _get_git_commit()
    inputs = {}

    for catchment in CATCHMENTS:
        for res in RESOLUTIONS:
            key = f"{catchment}_{res}m"
            file_path = extent_dir / f"{key}.csv"
            if not file_path.exists():
                raise FileNotFoundError(
                    f"Missing required case study extent file: {file_path}"
                )
            content = file_path.read_bytes()
            sha256_hash = hashlib.sha256(content).hexdigest()
            out = pd.read_csv(file_path)
            inputs[key] = {
                "catchment": catchment,
                "resolution_m": res,
                "file": f"extent/{key}.csv",
                "sha256": sha256_hash,
                "rows": len(out),
                "start": out["date"].iloc[0] if len(out) else START_DATE,
                "end": out["date"].iloc[-1] if len(out) else END_DATE,
            }

    manifest = {
        "source_product": "ga_ls_wo_3",
        "source_provider": "Geoscience Australia / Digital Earth Australia",
        "source_doi": "10.26186/146257",
        "source_license": "CC-BY-4.0",
        "stac_url": "https://explorer.dea.ga.gov.au/stac",
        "analysis_start": START_DATE,
        "analysis_end": END_DATE,
        "output_crs": "EPSG:3577",
        "generator_commit": commit,
        "inputs": inputs,
    }

    output_manifest.parent.mkdir(parents=True, exist_ok=True)
    output_manifest.write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def prepare_all_data(
    source_dir: Path = SOURCE_DIR,
    extent_dir: Path = EXTENT_DIR,
    output_manifest: Path = CASE_DATA_DIR / "manifest.json",
) -> dict:
    extent_dir.mkdir(parents=True, exist_ok=True)
    manifest_entries = {}

    for catchment in CATCHMENTS:
        for res in RESOLUTIONS:
            key = f"{catchment}_{res}m"
            src = source_dir / f"{key}_water_extent.csv"
            dst = extent_dir / f"{key}.csv"
            entry = normalize_extent_csv(
                src,
                dst,
                start=START_DATE,
                end=END_DATE,
                catchment=catchment,
                resolution=res,
            )
            manifest_entries[key] = entry

    return build_manifest(extent_dir, output_manifest)


def check_data_integrity(
    case_data_dir: Path = CASE_DATA_DIR,
) -> bool:
    manifest_path = case_data_dir / "manifest.json"
    if not manifest_path.exists():
        print(f"ERROR: Manifest missing: {manifest_path}", file=sys.stderr)
        return False

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    inputs = manifest.get("inputs", {})
    if len(inputs) != 20:
        print(f"ERROR: Manifest has {len(inputs)} inputs, expected 20", file=sys.stderr)
        return False

    errors = []
    for catchment in CATCHMENTS:
        for res in RESOLUTIONS:
            key = f"{catchment}_{res}m"
            if key not in inputs:
                errors.append(f"Missing key in manifest: {key}")
                continue
            entry = inputs[key]
            file_path = case_data_dir / entry["file"]
            if not file_path.exists():
                errors.append(f"File missing: {file_path}")
                continue
            actual_sha = hashlib.sha256(file_path.read_bytes()).hexdigest()
            if actual_sha != entry["sha256"]:
                errors.append(
                    f"Hash mismatch for {key}: manifest={entry['sha256']} actual={actual_sha}"
                )

    if errors:
        for err in errors:
            print(f"ERROR: {err}", file=sys.stderr)
        return False

    print("CHECK PASS: All 20 case study extent files and hashes are intact.")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify existing case_studies/data files against manifest",
    )
    args = parser.parse_args()

    if args.check:
        ok = check_data_integrity()
        sys.exit(0 if ok else 1)
    else:
        print("Preparing case study extent files...")
        manifest = prepare_all_data()
        print(f"Wrote {len(manifest['inputs'])} extent files and manifest.json.")


if __name__ == "__main__":
    main()
