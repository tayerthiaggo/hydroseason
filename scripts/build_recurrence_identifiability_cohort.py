"""Build the blinded real-catchment cycle cohort for recurrence review.

Discovers uninspected real catchments, applies boundary detection to define cycle
bounds, strips all decision columns, stratifies by cycle window span and
completeness, and outputs anonymized review packets.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd  # noqa: E402

from hydroseason import analyze_catchment  # noqa: E402
from scripts.build_timing_identifiability_cohort import strip_decision_columns  # noqa: E402


def validate_protocol(protocol: dict[str, Any]) -> dict[str, Any]:
    required_keys = {"protocol_id", "packet_allowlist", "hidden_fields", "excluded_sources"}
    missing = required_keys - set(protocol.keys())
    if missing:
        raise ValueError(f"protocol missing required keys: {sorted(missing)}")
    return protocol


def assert_source_eligible(source: Path, excluded_sources: list[str]) -> None:
    source_resolved = str(source.resolve()).replace("\\", "/").casefold()
    for token in excluded_sources:
        clean_token = token.strip().replace("\\", "/").casefold()
        tokens_to_check = [clean_token]
        if "/" in clean_token:
            tokens_to_check.append(clean_token.split("/")[-1])
        if any(t in source_resolved for t in tokens_to_check if t):
            raise ValueError(f"excluded source: {source} matches {token!r}")


def anonymous_id(seed: int, identifier: str) -> str:
    payload = f"{seed}:{identifier}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def write_identity_mapping(output_dir: Path, mapping: dict[str, str]) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    mapping_path = output_dir / "identity-mapping.json"
    hash_path = output_dir / "identity-mapping.sha256"

    content = json.dumps(mapping, indent=2, sort_keys=True).encode("utf-8")
    mapping_path.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    hash_path.write_text(f"{digest}\n", encoding="ascii")
    return mapping_path, hash_path


def discover_sources(source_root: Path) -> list[tuple[str, Path]]:
    sources: list[tuple[str, Path]] = []
    if not source_root.exists():
        return sources
    for p in sorted(source_root.glob("**/*_monthly.csv")):
        sid = p.parent.name.split("-", 1)[0].casefold()
        sources.append((sid, p))
    if not sources:
        for p in sorted(source_root.glob("*.csv")):
            sid = p.stem.split("_", 1)[0].casefold()
            sources.append((sid, p))
    return sources


def classify_stratum(window_start: pd.Timestamp, window_end: pd.Timestamp, observed_dates: set[pd.Timestamp]) -> str:
    full_months = pd.date_range(start=window_start, end=window_end, freq="MS")
    span = len(full_months)
    if span < 12:
        return "window_span_0_11"
    is_complete = all(m in observed_dates for m in full_months)
    return "window_span_12_plus_complete" if is_complete else "window_span_12_plus_gapped"


def build_cohort(
    *,
    source_root: Path,
    protocol: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    assert_source_eligible(source_root, protocol["excluded_sources"])
    seed = int(protocol.get("seed", 20260903))
    packet_allowlist = protocol["packet_allowlist"]

    sources = discover_sources(source_root)
    if not sources:
        raise ValueError(f"No eligible catchment sources found in {source_root}")

    catchment_cycles: dict[str, list[dict[str, Any]]] = defaultdict(list)
    identity_map: dict[str, str] = {}

    for sid, path in sources:
        raw_df = pd.read_csv(path)
        stripped = strip_decision_columns(raw_df, source=str(path))
        analysis = analyze_catchment(stripped)
        if analysis.hydro_years is None or analysis.hydro_years.empty:
            continue

        anon_catchment = anonymous_id(seed, sid)
        identity_map[anon_catchment] = sid

        date_col = "date" if "date" in stripped.columns else stripped.columns[0]
        stripped[date_col] = pd.to_datetime(stripped[date_col])
        observed_dates = set(stripped[date_col])

        for cycle_idx, row in analysis.hydro_years.iterrows():
            w_start = (
                pd.Timestamp(row["peak_window_start"])
                if "peak_window_start" in row
                else pd.Timestamp(row.get("trough_window_start", "2000-01-01"))
            )
            w_end = (
                pd.Timestamp(row["peak_window_end"])
                if "peak_window_end" in row
                else pd.Timestamp(row.get("trough_window_end", "2001-01-01"))
            )
            stratum = classify_stratum(w_start, w_end, observed_dates)
            anon_cycle = anonymous_id(seed, f"{sid}:{cycle_idx}:{w_start}")

            full_range = pd.date_range(start=w_start, end=w_end, freq="MS")
            window_obs = stripped[(stripped[date_col] >= w_start) & (stripped[date_col] <= w_end)].copy()
            merged = pd.DataFrame({date_col: full_range}).merge(window_obs, on=date_col, how="left")
            merged["anonymous_catchment_id"] = anon_catchment
            merged["anonymous_cycle_id"] = anon_cycle
            merged["window_start"] = w_start.strftime("%Y-%m-%d")
            merged["window_end"] = w_end.strftime("%Y-%m-%d")

            for col in packet_allowlist:
                if col not in merged.columns:
                    merged[col] = None

            packet_df = merged[packet_allowlist]
            catchment_cycles[anon_catchment].append({
                "anonymous_cycle_id": anon_cycle,
                "stratum": stratum,
                "df": packet_df,
            })

    stratum_catchments: dict[str, set[str]] = defaultdict(set)
    for anon_cid, cycles in catchment_cycles.items():
        for c in cycles:
            stratum_catchments[c["stratum"]].add(anon_cid)

    selected_catchments: set[str] = set()
    for stratum, cids in stratum_catchments.items():
        sorted_cids = sorted(cids, key=lambda x: hashlib.sha256(f"{seed}:{x}".encode()).hexdigest())
        chosen = sorted_cids[:8] if len(sorted_cids) >= 8 else sorted_cids
        selected_catchments.update(chosen)

    packets_dir = output_dir / "packets"
    packets_dir.mkdir(parents=True, exist_ok=True)
    packet_count = 0
    for anon_cid in selected_catchments:
        for c in catchment_cycles[anon_cid]:
            out_file = packets_dir / f"{c['anonymous_cycle_id']}.csv"
            c["df"].to_csv(out_file, index=False)
            packet_count += 1

    mapping_path, hash_path = write_identity_mapping(output_dir, identity_map)

    manifest = {
        "protocol_id": protocol["protocol_id"],
        "selected_catchments_count": len(selected_catchments),
        "packets_count": packet_count,
        "identity_mapping": str(mapping_path.relative_to(output_dir)),
        "identity_mapping_sha256": str(hash_path.relative_to(output_dir)),
    }
    (output_dir / "cohort-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    protocol = validate_protocol(json.loads(args.protocol.read_text(encoding="utf-8")))
    manifest = build_cohort(
        source_root=args.source_root,
        protocol=protocol,
        output_dir=args.output_dir,
    )
    print(
        f"Built {manifest['packets_count']} packets across "
        f"{manifest['selected_catchments_count']} catchments into {args.output_dir}"
    )


if __name__ == "__main__":
    main()