"""Stage 0 of the clock-anchor thread: does a frozen rise rule agree across tiles?

Reads hydropools' historical HydroSeason outputs read-only (per tile:
``channel_monthly_extent.csv`` and ``*_hydro_years.csv``) and the hydropools
output manifest (channel pixel counts). For every tile-year it locates the
first sustained departure from the trough band under ``RULE`` and scores how
well tiles agree on that month, against the end-dry hydropools uses today.

``RULE``, ``MARGIN`` and ``VARIANTS`` are frozen before any real data is read
(see docs/superpowers/plans/2026-10-30-clock-anchor-stage0.md, Task 7). They
are not method thresholds and nothing in ``hydroseason/`` uses them.

Example:

    .venv/Scripts/python.exe scripts/clock_anchor_stage0.py \
        --hydroseason-dir D:/RLH/5.6/repos/hydropools/work/rerun/fitzroy/hydroseason \
        --manifest D:/RLH/5.6/repos/hydropools/outputs/rerun/fitzroy/manifest.json \
        --out dev/reports/2026-10-30-clock-anchor-stage0.csv \
        --summary dev/reports/2026-10-30-clock-anchor-stage0.md \
        --receipt dev/reports/2026-10-30-clock-anchor-stage0.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

RULE = {
    "version": "stage0_rise_v1",
    "extent": "valid_denominator: extent_pct / (1 - invalid_pct / 100)",
    "level": "median of the valid-denominator extent over the trough band "
    "(trough_interval_start_date..trough_interval_end_date, else the boundary month)",
    "floor_pp_min": 1.0,
    "threshold": "level + max(detectability_floor_pp, floor_pp_min)",
    "search": "months after the trough band end up to and including the window end; "
    "abstain if the first post-band month is unobserved",
    "window_end": "next cycle's peak_date, else its peak_interval_start_date, "
    "else its trough_boundary_date",
    "confirm_max_gap_months": 2,
    "confirmation": "the next observed month, at most confirm_max_gap_months later and "
    "inside the window, must also exceed the threshold; a single exceedance followed by a "
    "return below it is a pulse and the search continues",
    "status": {
        "point": "confirmed, and the calendar month before the rise month was observed below "
        "the threshold",
        "interval": "confirmed, but the last observed low month is more than one month "
        "earlier (or the band-end month was not an observed low); interval = "
        "[last low month + 1, rise month]",
        "unconfirmed": "an exceedance with no following observation inside the window within "
        "confirm_max_gap_months",
        "no_rise": "nothing exceeds the threshold before the window end",
        "no_observed_months": "no observed month after the band end through the window end",
        "missing_first_post_band_month": "the first month after the band end is unobserved",
        "no_band_level": "no observed month inside the trough band",
        "no_window": "no boundary, no following cycle, or a window end at or before the boundary or band end",
    },
    "scored_month": "the rise month (first observed exceedance; the interval's end)",
    "scored_statuses": ["point", "interval"],
}

MARGIN = {
    "min_within_1": 0.90,
    "min_gain_over_end_dry": 0.05,
    "min_coverage": 0.90,
    "big_tile_min_px": 3000,
    "min_other_tiles": 3,
    "min_scored_tile_years": 500,
    "hy_first": 1988,
    "hy_last": 2025,
    "primary_metric": "pooled share of big-tile tile-years within +-1 month of the "
    "leave-target-out channel-pixel-weighted median of the same year",
    "coverage": "point + interval over all eligible big tile-years, including no_window",
}

HY_DATE_COLUMNS = [
    "trough_boundary_date",
    "trough_interval_start_date",
    "trough_interval_end_date",
    "trough_date",
    "peak_date",
    "peak_interval_start_date",
    "mid_dry_date",
]


def _month_axis(monthly: pd.DataFrame) -> pd.DatetimeIndex:
    stamps = pd.to_datetime(monthly["date"]).dt.to_period("M").dt.to_timestamp()
    return pd.DatetimeIndex(stamps)


def valid_denominator_extent(monthly: pd.DataFrame) -> pd.Series:
    """Hydropools exports 100*wet/n_aoi and 100*(n_aoi-obs)/n_aoi; their quotient is the valid-pixel extent."""
    extent = pd.to_numeric(monthly["extent_pct"], errors="coerce").to_numpy(dtype=float)
    invalid = pd.to_numeric(monthly["invalid_pct"], errors="coerce").to_numpy(dtype=float)
    observed = 1.0 - invalid / 100.0
    with np.errstate(divide="ignore", invalid="ignore"):
        values = np.where(
            np.isfinite(extent) & np.isfinite(observed) & (observed > 0.0),
            extent / observed,
            np.nan,
        )
    return pd.Series(values, index=_month_axis(monthly), name="valid_denominator_extent").sort_index()


def exported_extent(monthly: pd.DataFrame) -> pd.Series:
    """The exported ``extent_pct`` as is (denominator = all footprint pixels)."""
    extent = pd.to_numeric(monthly["extent_pct"], errors="coerce").to_numpy(dtype=float)
    return pd.Series(extent, index=_month_axis(monthly), name="exported_extent").sort_index()


def month_index(stamp) -> int:
    ts = pd.Timestamp(stamp)
    return ts.year * 12 + ts.month - 1


def month_from_index(k: int) -> pd.Timestamp:
    return pd.Timestamp(year=k // 12, month=k % 12 + 1, day=1)


def end_dry_as_run(row: pd.Series) -> pd.Timestamp | None:
    """hydropools ``seasons.dry_windows`` chain: point -> interval end -> boundary. No re-wet guard."""
    if row.get("trough_timing_status") == "point" and pd.notna(row.get("trough_date")):
        return pd.Timestamp(row["trough_date"])
    if pd.notna(row.get("trough_interval_end_date")):
        return pd.Timestamp(row["trough_interval_end_date"])
    if pd.notna(row.get("trough_boundary_date")):
        return pd.Timestamp(row["trough_boundary_date"])
    return None


def weighted_median(values, weights) -> float:
    """First value whose cumulative weight reaches half the total (the proposal's ``sync.py`` rule)."""
    values = np.asarray(values, dtype=float)
    weights = np.asarray(weights, dtype=float)
    order = np.argsort(values, kind="stable")
    cumulative = np.cumsum(weights[order])
    return float(values[order][np.searchsorted(cumulative, cumulative[-1] / 2.0)])


def leave_one_out_deviations(values, weights, *, min_other: int) -> np.ndarray:
    """Absolute distance of each value from the weighted median of the others; NaN if too few others."""
    values = np.asarray(values, dtype=float)
    weights = np.asarray(weights, dtype=float)
    out = np.full(len(values), np.nan)
    if len(values) - 1 < min_other:
        return out
    for i in range(len(values)):
        out[i] = abs(values[i] - weighted_median(np.delete(values, i), np.delete(weights, i)))
    return out


def _first_present(row: pd.Series, columns: tuple[str, ...]) -> pd.Timestamp | None:
    for col in columns:
        if pd.notna(row.get(col)):
            return pd.Timestamp(row[col])
    return None


def rise_month(
    values: pd.Series,
    row: pd.Series,
    next_row: pd.Series | None,
    *,
    floor_pp_min: float,
    confirm_max_gap_months: int,
) -> dict:
    """Apply ``RULE`` to one cycle. ``values`` is a month-start-indexed extent series."""
    out = dict(
        status=None,
        rise_month=pd.NaT,
        interval_start=pd.NaT,
        interval_end=pd.NaT,
        level_pp=np.nan,
        threshold_pp=np.nan,
        window_end=pd.NaT,
        band_start=pd.NaT,
        band_end=pd.NaT,
        n_pulses=0,
    )
    boundary = row.get("trough_boundary_date")
    if pd.isna(boundary) or next_row is None:
        out["status"] = "no_window"
        return out
    boundary = pd.Timestamp(boundary)
    window_end = _first_present(
        next_row, ("peak_date", "peak_interval_start_date", "trough_boundary_date")
    )
    if window_end is None or window_end <= boundary:
        out["status"] = "no_window"
        return out
    out["window_end"] = window_end

    band_start = row.get("trough_interval_start_date")
    band_end = row.get("trough_interval_end_date")
    if pd.isna(band_start) or pd.isna(band_end):
        band_start = band_end = boundary
    band_start, band_end = pd.Timestamp(band_start), pd.Timestamp(band_end)
    out["band_start"], out["band_end"] = band_start, band_end
    if window_end <= band_end:
        out["status"] = "no_window"
        return out
    band = values.loc[band_start:band_end].dropna()
    if band.empty:
        out["status"] = "no_band_level"
        return out
    level = float(band.median())
    floor = row.get("detectability_floor_pp")
    floor = float(floor) if pd.notna(floor) else 0.0
    threshold = level + max(floor, float(floor_pp_min))
    out.update(level_pp=level, threshold_pp=threshold)

    span = values.loc[band_end + pd.DateOffset(months=1) : window_end].dropna()
    if span.empty:
        out["status"] = "no_observed_months"
        return out
    first_post_band = band_end + pd.DateOffset(months=1)
    if pd.isna(values.get(first_post_band, np.nan)):
        out["status"] = "missing_first_post_band_month"
        return out
    k = np.array([month_index(stamp) for stamp in span.index])
    exceed = span.to_numpy(dtype=float) > threshold
    boundary_value = float(values.get(band_end, np.nan))
    last_low_k = (
        month_index(band_end)
        if np.isfinite(boundary_value) and boundary_value <= threshold
        else None
    )

    def _interval_start(rise_k: int) -> pd.Timestamp:
        start_k = last_low_k + 1 if last_low_k is not None else month_index(band_end) + 1
        return month_from_index(min(start_k, rise_k))

    pulses = 0
    i = 0
    while i < len(k):
        if not exceed[i]:
            last_low_k = int(k[i])
            i += 1
            continue
        j = i + 1
        if j >= len(k) or k[j] - k[i] > confirm_max_gap_months:
            out.update(
                status="unconfirmed",
                rise_month=span.index[i],
                interval_start=_interval_start(int(k[i])),
                interval_end=span.index[i],
                n_pulses=pulses,
            )
            return out
        if exceed[j]:
            bracketed = last_low_k is not None and last_low_k + 1 == int(k[i])
            out.update(
                status="point" if bracketed else "interval",
                rise_month=span.index[i],
                interval_start=_interval_start(int(k[i])),
                interval_end=span.index[i],
                n_pulses=pulses,
            )
            return out
        pulses += 1
        last_low_k = int(k[j])
        i = j + 1
    out.update(status="no_rise", n_pulses=pulses)
    return out


def synchrony(
    table: pd.DataFrame, month_col: str, *, big_tile_min_px: int, min_other_tiles: int
) -> dict:
    """Leave-target-out, channel-pixel-weighted agreement of big tiles on ``month_col`` per year."""
    rows = table.dropna(subset=[month_col])
    rows = rows[rows["px"] >= big_tile_min_px]
    deviations, per_year = [], []
    for _, group in rows.groupby("hy_year"):
        k = np.array([month_index(stamp) for stamp in group[month_col]])
        d = leave_one_out_deviations(k, group["px"].to_numpy(dtype=float), min_other=min_other_tiles)
        d = d[np.isfinite(d)]
        if d.size == 0:
            continue
        deviations.append(d)
        per_year.append(float((d <= 1).mean()))
    if not deviations:
        return dict(n_tile_years=0, n_years=0, pooled_within_1=np.nan, mean_within_1=np.nan, share_ge3=np.nan)
    d = np.concatenate(deviations)
    return dict(
        n_tile_years=int(d.size),
        n_years=len(per_year),
        pooled_within_1=float((d <= 1).mean()),
        mean_within_1=float(np.mean(per_year)),
        share_ge3=float((d >= 3).mean()),
    )


def decide(rise: dict, end_dry: dict, coverage: float) -> str:
    """Apply ``MARGIN``, including its scored tile-year data-sufficiency condition."""
    enough = (
        rise["n_tile_years"] >= MARGIN["min_scored_tile_years"]
        and end_dry["n_tile_years"] >= MARGIN["min_scored_tile_years"]
        and np.isfinite(rise["pooled_within_1"])
        and np.isfinite(end_dry["pooled_within_1"])
    )
    if not enough:
        return "INCONCLUSIVE"
    gain = rise["pooled_within_1"] - end_dry["pooled_within_1"]
    min_gain = MARGIN["min_gain_over_end_dry"]
    # Allow only a few machine epsilons for rounding in the subtraction.
    gain_passes = gain >= min_gain or np.isclose(gain, min_gain, rtol=0, atol=4 * np.finfo(float).eps)
    passed = (
        rise["pooled_within_1"] >= MARGIN["min_within_1"]
        and gain_passes
        and coverage >= MARGIN["min_coverage"]
    )
    return "PASS" if passed else "FAIL"


VARIANTS = (
    dict(name="primary", extent="valid_denominator", floor_pp_min=1.0, confirm_max_gap_months=2),
    dict(name="floor_2pp", extent="valid_denominator", floor_pp_min=2.0, confirm_max_gap_months=2),
    dict(name="floor_only", extent="valid_denominator", floor_pp_min=0.0, confirm_max_gap_months=2),
    dict(name="exported_extent", extent="exported", floor_pp_min=1.0, confirm_max_gap_months=2),
    dict(name="confirm_1", extent="valid_denominator", floor_pp_min=1.0, confirm_max_gap_months=1),
)


def channel_pixels(manifest_path: Path) -> dict[str, int]:
    manifest = json.loads(Path(manifest_path).read_text())
    return {region["name"]: int(region["channel_px"]) for region in manifest["summary"]["regions"]}


def load_tile(tile_dir: Path) -> tuple[str, pd.DataFrame, pd.DataFrame]:
    monthly = pd.read_csv(tile_dir / "channel_monthly_extent.csv")
    hy_paths = sorted(tile_dir.glob("*_hydro_years.csv"))
    if len(hy_paths) != 1:
        raise FileNotFoundError(f"{tile_dir}: expected one *_hydro_years.csv, found {len(hy_paths)}")
    hy = pd.read_csv(hy_paths[0])
    for col in HY_DATE_COLUMNS:
        hy[col] = pd.to_datetime(hy[col], errors="coerce")
    hy = hy.sort_values("hy_year").reset_index(drop=True)
    return tile_dir.name, monthly, hy


def evaluate_tile(
    tile: str,
    monthly: pd.DataFrame,
    hy: pd.DataFrame,
    px: int,
    *,
    extent: str,
    floor_pp_min: float,
    confirm_max_gap_months: int,
) -> list[dict]:
    values = valid_denominator_extent(monthly) if extent == "valid_denominator" else exported_extent(monthly)
    out = []
    for i in range(len(hy)):
        row = hy.iloc[i]
        year = int(row["hy_year"])
        if year < MARGIN["hy_first"] or year > MARGIN["hy_last"]:
            continue
        next_row = hy.iloc[i + 1] if i + 1 < len(hy) else None
        result = rise_month(
            values, row, next_row,
            floor_pp_min=floor_pp_min, confirm_max_gap_months=confirm_max_gap_months,
        )
        pre_rise = (
            result["rise_month"] - pd.DateOffset(months=1) if pd.notna(result["rise_month"]) else pd.NaT
        )
        out.append(
            dict(
                tile=tile,
                hy_year=year,
                px=px,
                boundary=row["trough_boundary_date"],
                trough_timing_status=row.get("trough_timing_status"),
                floor_pp=row.get("detectability_floor_pp"),
                end_dry_as_run=end_dry_as_run(row),
                pre_rise_month=pre_rise,
                **result,
            )
        )
    return out


def _variant_summary(sub: pd.DataFrame) -> dict:
    covered = sub["status"].isin(RULE["scored_statuses"])
    big = sub["px"] >= MARGIN["big_tile_min_px"]
    scored = sub.assign(scored_month=sub["rise_month"].where(covered))
    widths = (
        scored.loc[covered, "interval_end"].map(month_index) - scored.loc[covered, "interval_start"].map(month_index)
    )
    return dict(
        rise=synchrony(
            scored, "scored_month",
            big_tile_min_px=MARGIN["big_tile_min_px"], min_other_tiles=MARGIN["min_other_tiles"],
        ),
        coverage_big=float((covered & big).sum() / max(int(big.sum()), 1)),
        coverage_all=float(covered.sum() / max(len(sub), 1)),
        status_counts={str(k): int(v) for k, v in sub["status"].value_counts().items()},
        median_interval_width_months=float(widths.median()) if len(widths) else float("nan"),
        median_months_boundary_to_rise=float(
            (scored.loc[covered, "rise_month"].map(month_index) - scored.loc[covered, "boundary"].map(month_index)).median()
        ) if covered.any() else float("nan"),
    )


def run(hydroseason_dir: Path, manifest_path: Path) -> tuple[pd.DataFrame, dict]:
    px = channel_pixels(manifest_path)
    tile_dirs = sorted(path for path in Path(hydroseason_dir).iterdir() if path.is_dir())
    tiles = [load_tile(path) for path in tile_dirs]
    frames = []
    for variant in VARIANTS:
        options = {key: value for key, value in variant.items() if key != "name"}
        for tile, monthly, hy in tiles:
            if tile not in px:
                raise KeyError(f"{tile} is not a region in {manifest_path}")
            frame = pd.DataFrame(evaluate_tile(tile, monthly, hy, px[tile], **options))
            frame["variant"] = variant["name"]
            frames.append(frame)
    table = pd.concat(frames, ignore_index=True)
    primary = table[table["variant"] == "primary"]
    end_dry = synchrony(
        primary[primary["status"].ne("no_window")], "end_dry_as_run",
        big_tile_min_px=MARGIN["big_tile_min_px"], min_other_tiles=MARGIN["min_other_tiles"],
    )
    summary = {
        "n_tiles": len(tiles),
        "n_big_tiles": int(sum(px[tile] >= MARGIN["big_tile_min_px"] for tile, _, _ in tiles)),
        "end_dry_as_run": end_dry,
        "variants": {
            variant["name"]: _variant_summary(table[table["variant"] == variant["name"]])
            for variant in VARIANTS
        },
    }
    summary["decision"] = decide(
        summary["variants"]["primary"]["rise"], end_dry, summary["variants"]["primary"]["coverage_big"]
    )
    return table, summary


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _git_head() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
            cwd=Path(__file__).resolve().parent.parent, check=False,
        )
        return result.stdout.strip() or "unknown"
    except OSError:
        return "unknown"


def receipt(hydroseason_dir: Path, manifest_path: Path, summary: dict) -> dict:
    hydroseason_dir = Path(hydroseason_dir)
    inputs = {
        path.relative_to(hydroseason_dir).as_posix(): _sha256(path)
        for path in sorted(hydroseason_dir.rglob("*.csv"))
        if path.name == "channel_monthly_extent.csv" or path.name.endswith("_hydro_years.csv")
    }
    return dict(
        rule=RULE,
        margin=MARGIN,
        variants=list(VARIANTS),
        script_sha256=_sha256(Path(__file__)),
        git_head=_git_head(),
        manifest_sha256=_sha256(manifest_path),
        inputs=inputs,
        numpy=np.__version__,
        pandas=pd.__version__,
        decision=summary["decision"],
        summary=summary,
    )


def _fmt(value, digits=3) -> str:
    try:
        return f"{float(value):.{digits}f}" if np.isfinite(float(value)) else "n/a"
    except (TypeError, ValueError):
        return "n/a"


def to_markdown(summary: dict) -> str:
    end_dry = summary["end_dry_as_run"]
    lines = [
        f"Decision (primary variant, frozen margin): **{summary['decision']}**",
        "",
        f"Tiles read: {summary['n_tiles']} ({summary['n_big_tiles']} with channel_px >= "
        f"{MARGIN['big_tile_min_px']}). Scored years {MARGIN['hy_first']}-{MARGIN['hy_last']}.",
        "",
        "End-dry as run (hydropools chain, no re-wet guard): "
        f"pooled within +-1 = {_fmt(end_dry['pooled_within_1'])}, mean of years = "
        f"{_fmt(end_dry['mean_within_1'])}, >=3 off = {_fmt(end_dry['share_ge3'])}, "
        f"n = {end_dry['n_tile_years']} tile-years over {end_dry['n_years']} years.",
        "",
        "| variant | within +-1 (pooled) | within +-1 (mean of years) | >=3 off | n tile-years "
        "| coverage big | coverage all | median interval width | median boundary->rise | statuses |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for name, item in summary["variants"].items():
        rise = item["rise"]
        statuses = ", ".join(f"{key} {value}" for key, value in sorted(item["status_counts"].items()))
        lines.append(
            f"| {name} | {_fmt(rise['pooled_within_1'])} | {_fmt(rise['mean_within_1'])} "
            f"| {_fmt(rise['share_ge3'])} | {rise['n_tile_years']} | {_fmt(item['coverage_big'])} "
            f"| {_fmt(item['coverage_all'])} | {_fmt(item['median_interval_width_months'], 1)} "
            f"| {_fmt(item['median_months_boundary_to_rise'], 1)} | {statuses} |"
        )
    lines += [
        "",
        f"Margin: within +-1 >= {MARGIN['min_within_1']}, gain over end-dry >= "
        f"{MARGIN['min_gain_over_end_dry']}, coverage (big tiles) >= {MARGIN['min_coverage']}, "
        f"at least {MARGIN['min_scored_tile_years']} scored tile-years. Only the primary variant decides.",
    ]
    return "\n".join(lines) + "\n"


def _json_safe(value):
    """Replace non-finite numeric metrics with JSON null recursively."""
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (float, np.floating)) and not np.isfinite(value):
        return None
    return value


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--hydroseason-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args(argv)

    table, summary = run(args.hydroseason_dir, args.manifest)
    for path in (args.out, args.summary, args.receipt):
        path.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(args.out, index=False)
    args.summary.write_text(to_markdown(summary), encoding="utf-8")
    args.receipt.write_text(
        json.dumps(_json_safe(receipt(args.hydroseason_dir, args.manifest, summary)), indent=1, default=str, allow_nan=False),
        encoding="utf-8",
    )
    print(f"decision={summary['decision']} rows={len(table)} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
