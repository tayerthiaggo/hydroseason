"""Event-based characterisation of a surface-water record.

The annual-cycle view (peak, trough, hydrological year) presumes a
reproducible yearly rhythm. Where a catchment has none -- episodic dryland
rivers fill on rainfall events rather than on a calendar -- that view has
nothing to attach to, and forcing it produces boundaries that describe noise.

This module supplies the alternative vocabulary such records *do* satisfy:
discrete wet episodes, the dry spells between them, and how often filling
recurs. These are the terms in which an intermittent river is normally
described, and unlike a hydrological year they make no stationarity or
periodicity assumption.

Episode detection uses **hysteresis**: an event opens when extent rises above
a high threshold and stays open until it falls below a lower one. A single
entry threshold would split one flood into several whenever the recession
wobbles across it, inflating the event count precisely on the noisy records
this module exists to serve.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ._state_input import QualityPolicy, prepare_monthly_extent

_DEFAULT_START_QUANTILE = 0.75
_DEFAULT_END_QUANTILE = 0.50
_DEFAULT_LOW_QUANTILE = 0.20

# Multiples of the record's own noise scale, measured above/below its baseline
# median. Grounding the thresholds in noise rather than in a bare quantile
# makes them mean the same thing across catchments: "a departure larger than
# this record's month-to-month wobble", not "the top quarter of whatever this
# record happens to contain" -- a quantile puts 25% of months above the entry
# threshold even on a record with no events at all.
# 3.0 rather than 2.0: at 2 sigma roughly 2% of months clear the bar by chance,
# so a 40-year record accrues ~11 spurious one-month "floods". At 3 sigma that
# falls to ~0.1%. The choice is corroborated on real data -- Daly returns 38
# events across 39 usable years, recovering its known annual monsoon flood
# without being told the record is seasonal, where 2 sigma returns 45.
_DEFAULT_ENTER_K = 3.0
_DEFAULT_EXIT_K = 1.0
_DEFAULT_LOW_K = 1.0

# Below this fraction of the record's 10-90 spread, the noise estimate is not a
# usable scale (a synthetic or heavily-quantised record can have literally zero
# month-to-month variation) and thresholds fall back to quantiles.
_DEGENERATE_NOISE_FRACTION = 0.01


@dataclass(frozen=True)
class WaterEventResult:
    """Wet episodes, dry spells, and record-level summaries."""

    events: pd.DataFrame
    low_spells: pd.DataFrame
    summary: dict


def _empty_events() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "event_id", "start", "end", "duration_months", "peak_month",
            "peak_extent_pct", "mean_extent_pct", "magnitude_pp_months",
        ]
    )


def _empty_low_spells() -> pd.DataFrame:
    return pd.DataFrame(
        columns=["spell_id", "start", "end", "duration_months", "min_extent_pct"]
    )


def _noise_scale(values: pd.Series) -> float:
    """Robust month-to-month noise scale, AR(1)-corrected.

    Mirrors ``hydro_year._noise_floor_pp``: successive differences of a
    persistent series recover ``sigma*sqrt(1-phi)`` rather than ``sigma``, and
    dryland records are strongly persistent, so the raw estimate would badly
    under-read exactly where events matter most.
    """
    clean = values.dropna().astype(float)
    if len(clean) < 3:
        return 0.0
    delta = clean.diff().dropna().to_numpy(float)
    if not len(delta):
        return 0.0
    centre = float(np.median(delta))
    scale = 1.4826 * float(np.median(np.abs(delta - centre))) / np.sqrt(2.0)
    phi = float(pd.Series(clean.to_numpy(float)).autocorr(1) or 0.0)
    phi = min(max(phi, 0.0), 0.9)
    return scale / np.sqrt(1.0 - phi)


def _contiguous_blocks(flags: pd.Series) -> list[tuple[int, int]]:
    """Positional [start, end] pairs of each run of True in ``flags``."""
    blocks: list[tuple[int, int]] = []
    start: int | None = None
    for position, value in enumerate(flags.to_numpy()):
        if value and start is None:
            start = position
        elif not value and start is not None:
            blocks.append((start, position - 1))
            start = None
    if start is not None:
        blocks.append((start, len(flags) - 1))
    return blocks


def _merge_close_blocks(
    blocks: list[tuple[int, int]], min_separation: int
) -> list[tuple[int, int]]:
    """Join blocks separated by fewer than ``min_separation`` months.

    A recession that dips under the exit threshold for a month or two is one
    flood, not several; without this the event count inflates on exactly the
    noisy records the event view exists to describe.
    """
    if not blocks or min_separation <= 1:
        return blocks
    merged = [blocks[0]]
    for start, end in blocks[1:]:
        previous_start, previous_end = merged[-1]
        if start - previous_end - 1 < min_separation:
            merged[-1] = (previous_start, end)
        else:
            merged.append((start, end))
    return merged


def _years_without_event(usable_values: pd.Series, events: pd.DataFrame) -> int:
    """Count calendar years of usable record containing no wet event."""
    years = {int(year) for year in usable_values.index.year}
    if not years or events.empty:
        return len(years)
    covered: set[int] = set()
    for row in events.itertuples():
        span = pd.date_range(row.start, row.end, freq="MS")
        covered.update(int(stamp.year) for stamp in span)
    return len(years - covered)


def extract_water_events(
    extent,
    *,
    value_col: str = "extent_pct",
    date_col: str | None = None,
    threshold_mode: str = "noise",
    enter_k: float = _DEFAULT_ENTER_K,
    exit_k: float = _DEFAULT_EXIT_K,
    low_k: float = _DEFAULT_LOW_K,
    start_quantile: float = _DEFAULT_START_QUANTILE,
    end_quantile: float = _DEFAULT_END_QUANTILE,
    low_quantile: float = _DEFAULT_LOW_QUANTILE,
    min_event_months: int = 1,
    min_separation_months: int = 1,
    min_low_months: int = 2,
    max_invalid_pct: float = 20.0,
    quality_policy: QualityPolicy = "exclude",
) -> WaterEventResult:
    """Extract wet episodes and dry spells from a monthly extent record.

    **A wet event** is a departure above the record's baseline exceeding
    ``enter_k`` noise scales, persisting until it falls back below ``exit_k``
    noise scales (hysteresis), lasting at least ``min_event_months``, and
    separated from the next episode by at least ``min_separation_months``.

    **A low-extent spell** is a run of at least ``min_low_months`` below the
    baseline minus ``low_k`` noise scales. It is defined *independently of
    events*: a catchment that never floods still has low-extent spells, and
    defining a spell as the gap between two events reports none for exactly
    the records that stay low.

    The name is deliberate. This measures **below this record's own typical
    extent**, not dryness in the cease-to-flow sense -- roughly a third of all
    months qualify on a normal catchment, and calling those "dry" implies an
    absence of water that the data does not show. ``months_below_low_pct`` is
    reported alongside so the base rate is always visible: a long spell on a
    catchment where 38% of months sit below baseline describes a sustained
    below-average period, not a river without water.

    ``threshold_mode`` selects how those thresholds resolve:

    ``"noise"`` (default)
        Baseline median plus/minus multiples of the record's own AR(1)-corrected
        month-to-month noise. Means the same thing across catchments -- "larger
        than this record's own wobble" -- and presupposes nothing about what
        fraction of months are wet.
    ``"quantile"``
        Fixed quantiles of the usable distribution. Robust but arbitrary: p75
        places a quarter of all months above the entry threshold even on a
        record containing no events whatsoever.

    Where the noise estimate is degenerate -- a synthetic or heavily-quantised
    record with no month-to-month variation -- noise mode cannot produce a
    scale, so thresholds fall back to quantiles and the resolved mode is
    reported as ``"quantile_fallback"`` rather than silently claiming
    ``"noise"``.

    Months screened out by the quality policy break an episode rather than
    bridging it: an unobserved month is not evidence that water persisted.
    """
    if threshold_mode not in {"noise", "quantile"}:
        raise ValueError("threshold_mode must be 'noise' or 'quantile'.")
    if not 0.0 < end_quantile <= start_quantile < 1.0:
        raise ValueError("require 0 < end_quantile <= start_quantile < 1.")
    if not 0.0 < low_quantile < 1.0:
        raise ValueError("require 0 < low_quantile < 1.")
    if exit_k > enter_k:
        raise ValueError("exit_k must not exceed enter_k; hysteresis requires exit <= enter.")
    if min_event_months < 1 or min_separation_months < 1 or min_low_months < 1:
        raise ValueError("month thresholds must be positive.")

    prepared = prepare_monthly_extent(
        extent, value_col=value_col, date_col=date_col,
        max_invalid_pct=max_invalid_pct, quality_policy=quality_policy,
    )
    usable_values = prepared.loc[prepared["candidate_usable"], value_col].dropna()
    if usable_values.empty:
        return WaterEventResult(_empty_events(), _empty_low_spells(), {
            "n_events": 0, "n_low_spells": 0, "longest_low_spell_months": 0,
            "median_recurrence_months": 0.0, "median_event_duration_months": 0.0,
            "threshold_mode": threshold_mode, "baseline_pct": np.nan,
            "enter_threshold_pct": np.nan, "exit_threshold_pct": np.nan,
            "low_threshold_pct": np.nan, "noise_scale_pp": np.nan,
            "months_below_low_pct": 0.0, "years_without_event": 0,
            "min_event_months": min_event_months,
            "min_separation_months": min_separation_months,
            "min_low_months": min_low_months, "n_usable_months": 0,
        })

    baseline = float(usable_values.median())
    noise = _noise_scale(usable_values)
    spread = float(usable_values.quantile(0.90) - usable_values.quantile(0.10))
    degenerate = noise <= max(spread, 1e-12) * _DEGENERATE_NOISE_FRACTION

    if threshold_mode == "noise" and not degenerate:
        resolved_mode = "noise"
        enter_threshold = baseline + enter_k * noise
        exit_threshold = baseline + exit_k * noise
        low_threshold = baseline - low_k * noise
    else:
        resolved_mode = "quantile_fallback" if threshold_mode == "noise" else "quantile"
        enter_threshold = float(usable_values.quantile(start_quantile))
        exit_threshold = float(usable_values.quantile(end_quantile))
        low_threshold = float(usable_values.quantile(low_quantile))
        # A dry threshold must sit below the typical condition to mean
        # anything. On a record whose low tail is short, or heavily quantised,
        # the nominal quantile can land exactly on the median and select every
        # month or none. Drop to the highest observed value that is genuinely
        # below the baseline; if there is none, the record has no low tail and
        # no dry spell is reported.
        if low_threshold >= baseline:
            lower = usable_values[usable_values < baseline]
            low_threshold = float(lower.max()) if not lower.empty else float("-inf")

    series = prepared[value_col].where(prepared["candidate_usable"])
    observed = series.notna()

    # Hysteresis walk: open above the entry threshold, hold until the value
    # falls below the (lower) exit threshold. An unobserved month closes the
    # episode -- see docstring.
    in_event = np.zeros(len(series), dtype=bool)
    active = False
    for position, (value, seen) in enumerate(zip(series.to_numpy(), observed.to_numpy())):
        if not seen:
            active = False
            continue
        active = value > exit_threshold if active else value > enter_threshold
        in_event[position] = active

    blocks = _contiguous_blocks(pd.Series(in_event, index=series.index))
    blocks = _merge_close_blocks(blocks, min_separation_months)
    blocks = [(a, b) for a, b in blocks if (b - a + 1) >= min_event_months]

    rows = []
    for event_id, (first, last) in enumerate(blocks, start=1):
        window = series.iloc[first : last + 1].dropna()
        if window.empty:
            continue
        rows.append({
            "event_id": event_id,
            "start": series.index[first],
            "end": series.index[last],
            "duration_months": last - first + 1,
            "peak_month": window.idxmax(),
            "peak_extent_pct": round(float(window.max()), 6),
            "mean_extent_pct": round(float(window.mean()), 6),
            # Integrated excess over the exit threshold: separates a brief
            # high spike from a sustained inundation of the same peak height.
            "magnitude_pp_months": round(
                float((window - exit_threshold).clip(lower=0).sum()), 6
            ),
        })
    events = pd.DataFrame(rows) if rows else _empty_events()

    # Dry spells: runs below the dry threshold, independent of any event.
    below = pd.Series((series <= low_threshold) & observed, index=series.index)
    spell_blocks = [
        (a, b) for a, b in _contiguous_blocks(below) if (b - a + 1) >= min_low_months
    ]
    spell_rows = []
    for spell_id, (first, last) in enumerate(spell_blocks, start=1):
        window = series.iloc[first : last + 1].dropna()
        spell_rows.append({
            "spell_id": spell_id,
            "start": series.index[first],
            "end": series.index[last],
            "duration_months": last - first + 1,
            "min_extent_pct": round(float(window.min()), 6) if not window.empty else np.nan,
        })
    low_spells = pd.DataFrame(spell_rows) if spell_rows else _empty_low_spells()

    recurrence = 0.0
    if len(events) > 1:
        gaps = pd.to_datetime(events["start"]).diff().dropna().dt.days / 30.44
        recurrence = round(float(gaps.median()), 2)

    summary = {
        "n_events": int(len(events)),
        "n_low_spells": int(len(low_spells)),
        "longest_low_spell_months": (
            int(low_spells["duration_months"].max()) if not low_spells.empty else 0
        ),
        # Base rate, always reported: without it a long spell reads as drought
        # even when the threshold is one a third of all months sit below.
        "months_below_low_pct": round(
            100.0 * float((usable_values <= low_threshold).mean()), 1
        ),
        "years_without_event": _years_without_event(usable_values, events),
        "median_recurrence_months": recurrence,
        "median_event_duration_months": (
            float(events["duration_months"].median()) if not events.empty else 0.0
        ),
        "threshold_mode": resolved_mode,
        "baseline_pct": round(baseline, 6),
        "enter_threshold_pct": round(enter_threshold, 6),
        "exit_threshold_pct": round(exit_threshold, 6),
        "low_threshold_pct": round(low_threshold, 6),
        "noise_scale_pp": round(noise, 6),
        "min_event_months": min_event_months,
        "min_separation_months": min_separation_months,
        "min_low_months": min_low_months,
        "n_usable_months": int(len(usable_values)),
    }
    return WaterEventResult(events, low_spells, summary)


__all__ = ["WaterEventResult", "extract_water_events"]
