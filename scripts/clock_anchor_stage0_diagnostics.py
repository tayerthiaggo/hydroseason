"""Post-hoc diagnostics for the stage-0 clock-anchor run.

Everything here was computed after the decision and does not change it. The
frozen rule, margin and variants in ``scripts/clock_anchor_stage0.py`` are
imported, never redefined. The script reads the per-row table and receipt the
frozen run wrote and, when ``--hydroseason-dir`` is given, the same hydropools
inputs the receipt hashed (it refuses to run if any of them changed).

Usage::

    python scripts/clock_anchor_stage0_diagnostics.py \\
        --rows docs/handoff/2026-10-30-clock-anchor-stage0-rows.csv.gz \\
        --receipt docs/handoff/2026-10-30-clock-anchor-stage0-receipt.json \\
        --hydroseason-dir D:/RLH/5.6/repos/hydropools/work/rerun/fitzroy/hydroseason \\
        --out docs/handoff/2026-10-30-clock-anchor-stage0-diagnostics.json
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.clock_anchor_stage0 import (
    MARGIN,
    RULE,
    leave_one_out_deviations,
    load_tile,
    month_index,
    synchrony,
    valid_denominator_extent,
)

FROZEN_SCRIPT = Path(__file__).with_name("clock_anchor_stage0.py")
ROW_DATE_COLUMNS = (
    "boundary", "end_dry_as_run", "pre_rise_month", "rise_month", "interval_start",
    "interval_end", "window_end", "band_start", "band_end",
)
EPSILON_TILES = ("tile05", "tile13", "tile18", "tile46")
BOOTSTRAP_DRAWS = 4000
BOOTSTRAP_SEED = 0


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def lf_bytes(path: Path) -> bytes:
    """File bytes with CRLF folded to LF, so the hash is the same on every OS."""
    return Path(path).read_bytes().replace(b"\r\n", b"\n")


def read_rows_bytes(path: Path) -> bytes:
    """Return the uncompressed CSV bytes the frozen run wrote."""
    data = Path(path).read_bytes()
    return gzip.decompress(data) if str(path).endswith(".gz") else data


def load_rows(path: Path) -> pd.DataFrame:
    rows = pd.read_csv(path)
    for column in ROW_DATE_COLUMNS:
        rows[column] = pd.to_datetime(rows[column])
    return rows


def script_hashes(path: Path = FROZEN_SCRIPT) -> dict:
    """Hash the frozen script with LF and with CRLF line endings.

    The receipt hashed the Windows working-tree file (CRLF under
    ``core.autocrlf=true``). Git stores LF, so a checkout on Linux or macOS
    hashes differently. Both forms identify the same committed script.
    """
    lf = lf_bytes(path)
    return dict(lf=sha256_bytes(lf), crlf=sha256_bytes(lf.replace(b"\n", b"\r\n")))


def _kw() -> dict:
    return dict(big_tile_min_px=MARGIN["big_tile_min_px"], min_other_tiles=MARGIN["min_other_tiles"])


def _year_deviations(rows: pd.DataFrame, columns: tuple[str, ...]) -> dict[int, list[np.ndarray]]:
    """Leave-target-out deviations per year for each month column, on the same rows."""
    out = {}
    for year, group in rows.groupby("hy_year"):
        weights = group["px"].to_numpy(dtype=float)
        devs = [
            leave_one_out_deviations(
                np.array([month_index(stamp) for stamp in group[column]]), weights,
                min_other=MARGIN["min_other_tiles"],
            )
            for column in columns
        ]
        keep = np.all([np.isfinite(d) for d in devs], axis=0)
        if keep.any():
            out[int(year)] = [d[keep] for d in devs]
    return out


def row_diagnostics(rows: pd.DataFrame) -> dict:
    """Diagnostics that need only the per-row table (primary variant)."""
    primary = rows[rows["variant"] == "primary"].copy()
    big = primary["px"] >= MARGIN["big_tile_min_px"]
    scored = primary["status"].isin(RULE["scored_statuses"])
    end_dry_rows = primary["status"].ne("no_window") & primary["end_dry_as_run"].notna()

    matched = primary[scored].assign(scored_month=primary.loc[scored, "rise_month"])
    rise = synchrony(matched, "scored_month", **_kw())
    end_dry_matched = synchrony(matched, "end_dry_as_run", **_kw())
    agree = int(round(rise["pooled_within_1"] * rise["n_tile_years"]))

    rng = np.random.default_rng(BOOTSTRAP_SEED)
    big_scored = matched[matched["px"] >= MARGIN["big_tile_min_px"]]
    paired = _year_deviations(big_scored, ("scored_month", "end_dry_as_run"))
    years = sorted(paired)
    within, gain = [], []
    for _ in range(BOOTSTRAP_DRAWS):
        pick = rng.choice(years, size=len(years))
        d_rise = np.concatenate([paired[y][0] for y in pick])
        d_end = np.concatenate([paired[y][1] for y in pick])
        within.append(float((d_rise <= 1).mean()))
        gain.append(float((d_rise <= 1).mean() - (d_end <= 1).mean()))
    within, gain = np.array(within), np.array(gain)

    unconfirmed = primary[primary["status"] == "unconfirmed"]
    at_window_end = unconfirmed["rise_month"].eq(unconfirmed["window_end"])
    px = primary.groupby("tile")["px"].first()
    return dict(
        n_big_tile_years=int(big.sum()),
        n_scored_big_tile_years=int((scored & big).sum()),
        end_dry_coverage_big=float((end_dry_rows & big).sum() / big.sum()),
        rise_agree=agree,
        rise_n=int(rise["n_tile_years"]),
        rise_pooled_within_1=float(rise["pooled_within_1"]),
        rise_pooled_within_1_one_fewer=float((agree - 1) / rise["n_tile_years"]),
        end_dry_matched_pooled_within_1=float(end_dry_matched["pooled_within_1"]),
        end_dry_matched_n=int(end_dry_matched["n_tile_years"]),
        matched_gain=float(rise["pooled_within_1"] - end_dry_matched["pooled_within_1"]),
        bootstrap=dict(
            draws=BOOTSTRAP_DRAWS,
            seed=BOOTSTRAP_SEED,
            unit="hydrological year (block), big tiles, rows scored by both methods",
            within_1_ci95=[float(np.percentile(within, 2.5)), float(np.percentile(within, 97.5))],
            share_within_1_below_margin=float((within < MARGIN["min_within_1"]).mean()),
            matched_gain_ci95=[float(np.percentile(gain, 2.5)), float(np.percentile(gain, 97.5))],
        ),
        n_unconfirmed=int(len(unconfirmed)),
        n_unconfirmed_big=int((unconfirmed["px"] >= MARGIN["big_tile_min_px"]).sum()),
        n_unconfirmed_at_window_end=int(at_window_end.sum()),
        big_tile_status_counts={str(k): int(v) for k, v in primary.loc[big, "status"].value_counts().items()},
        epsilon_tile_px={tile: int(px[tile]) for tile in EPSILON_TILES},
        max_epsilon_tile_px=int(max(px[tile] for tile in EPSILON_TILES)),
    )


def _verify_inputs(hydroseason_dir: Path, receipt: dict) -> None:
    changed = [
        name for name, digest in receipt["inputs"].items()
        if sha256_bytes((Path(hydroseason_dir) / name).read_bytes()) != digest
    ]
    if changed:
        raise SystemExit(f"inputs changed since the frozen run: {changed}")


def input_diagnostics(rows: pd.DataFrame, hydroseason_dir: Path, receipt: dict) -> dict:
    """Diagnostics that read the monthly extent inputs the receipt hashed."""
    _verify_inputs(hydroseason_dir, receipt)
    extent = {}
    for tile_dir in sorted(path for path in Path(hydroseason_dir).iterdir() if path.is_dir()):
        tile, monthly, _ = load_tile(tile_dir)
        series = valid_denominator_extent(monthly)
        extent[tile] = pd.Series(series.to_numpy(dtype=float), index=[month_index(t) for t in series.index])

    primary = rows[rows["variant"] == "primary"]
    big_total = int((primary["px"] >= MARGIN["big_tile_min_px"]).sum())
    gap = RULE["confirm_max_gap_months"]
    records = []
    for row in primary[primary["status"] == "unconfirmed"].itertuples():
        series = extent[row.tile]
        band_end_k, window_end_k, rise_k = (
            month_index(row.band_end), month_index(row.window_end), month_index(row.rise_month)
        )
        pre_peak = series[(series.index > band_end_k) & (series.index < window_end_k)]
        expected = window_end_k - band_end_k - 1
        later = series[(series.index > rise_k) & (series.index <= rise_k + gap)].dropna()
        records.append(dict(
            big=row.px >= MARGIN["big_tile_min_px"],
            pre_peak_missing=expected - int(pre_peak.notna().sum()),
            no_pre_peak_month=expected == 0,
            flat_until_peak=bool(expected > 0 and int(pre_peak.notna().sum()) == expected
                                 and (pre_peak.dropna() <= row.threshold_pp).all()),
            would_confirm=bool(len(later) and later.iloc[0] > row.threshold_pp),
            jump_pp=float(series.get(rise_k, np.nan) - row.level_pp),
            prior_pp=float(series.get(rise_k - 1, np.nan) - row.level_pp),
        ))
    table = pd.DataFrame(records)
    big = table[table["big"]]
    point_interval_big = int(
        ((primary["px"] >= MARGIN["big_tile_min_px"]) & primary["status"].isin(RULE["scored_statuses"])).sum()
    )
    quantiles = [0.1, 0.25, 0.5, 0.75, 0.9]
    return dict(
        inputs_verified=len(receipt["inputs"]),
        unconfirmed_share_with_unobserved_pre_peak_month=float((table["pre_peak_missing"] > 0).mean()),
        n_unconfirmed_no_pre_peak_month=int(table["no_pre_peak_month"].sum()),
        n_unconfirmed_flat_until_peak=int(table["flat_until_peak"].sum()),
        n_unconfirmed_would_confirm_if_window_extended=int(table["would_confirm"].sum()),
        n_unconfirmed_big_would_confirm_if_window_extended=int(big["would_confirm"].sum()),
        hypothetical_coverage_big_if_window_extended=float(
            (point_interval_big + int(big["would_confirm"].sum())) / big_total
        ),
        big_unconfirmed_jump_pp_quantiles=dict(zip(map(str, quantiles), map(float, big["jump_pp"].quantile(quantiles)))),
        big_unconfirmed_prior_month_pp_median=float(big["prior_pp"].median()),
        big_unconfirmed_share_jump_ge_5pp=float((big["jump_pp"] >= 5).mean()),
        big_unconfirmed_share_jump_lt_2pp=float((big["jump_pp"] < 2).mean()),
    )


def build(rows_path: Path, receipt_path: Path, hydroseason_dir: Path | None) -> dict:
    receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    rows_bytes = read_rows_bytes(rows_path)
    rows = load_rows(rows_path)
    hashes = script_hashes()
    if hashes["crlf"] != receipt["script_sha256"] and hashes["lf"] != receipt["script_sha256"]:
        raise SystemExit("scripts/clock_anchor_stage0.py differs from the script the receipt hashed")
    out = dict(
        note="Post-hoc diagnostics computed after the stage-0 decision; they do not change it.",
        receipt_sha256_lf=sha256_bytes(lf_bytes(receipt_path)),
        rows_csv_sha256=sha256_bytes(rows_bytes),
        frozen_script_sha256=hashes,
        rows=row_diagnostics(rows),
    )
    if hydroseason_dir is not None:
        out["inputs"] = input_diagnostics(rows, hydroseason_dir, receipt)
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rows", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--hydroseason-dir", type=Path, default=None)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    result = build(args.rows, args.receipt, args.hydroseason_dir)
    args.out.write_text(json.dumps(result, indent=1, allow_nan=False) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
