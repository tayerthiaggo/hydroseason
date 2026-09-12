"""Known-truth records for validating the seasonality candidate.

One partition only: the candidate fits nothing, so there is no calibration
set to keep separate. Seeds are disjoint from every existing corpus.
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np
import pandas as pd

SEASONALITY_VALIDATION_SEEDS = range(90000, 95000)
_BASE_ENTROPY = 90000

_CENTRE_PCT = 50.0
_AMPLITUDE_PCT = 5.0
_NOISE_SD_PCT = 2.5
_TREND_TOTAL_PCT = 40.0
_STRONG_TREND_TOTAL_PCT = 72.0
_STRONG_TREND_NOISE_SD_PCT = 1.0
_STEP_PCT = 20.0
_EVENT_PROBABILITY = 0.08
_EVENT_DECAY_MONTHS = 1.5
_EVENT_BURN_IN_MONTHS = 120
_PULSE_LEVEL_PCT = 30.0
_PULSE_NOISE_SD_PCT = 2.0
_LOW_EXTENT_SCALE = 0.02
_PIXEL_N_AOI = 1000
_MAX_ATTEMPTS = 50

VARIANTS = ("base", "missing_10", "missing_25", "low_state_gap", "pixel_rounded")


@dataclass(frozen=True)
class SeasonalityFamily:
    family_id: int
    name: str
    truth_seasonal: bool | None


SEASONALITY_FAMILIES: tuple[SeasonalityFamily, ...] = (
    SeasonalityFamily(1, "white_noise", False),
    SeasonalityFamily(2, "ar1_0_5", False),
    SeasonalityFamily(3, "ar1_0_8", False),
    SeasonalityFamily(4, "trend", False),
    SeasonalityFamily(5, "strong_trend", False),
    SeasonalityFamily(6, "step", False),
    SeasonalityFamily(7, "events", False),
    SeasonalityFamily(8, "all_zero", False),
    SeasonalityFamily(21, "sinusoid", True),
    SeasonalityFamily(22, "narrow_pulse", True),
    SeasonalityFamily(23, "asymmetric", True),
    SeasonalityFamily(24, "annual_plus_trend", True),
    SeasonalityFamily(25, "annual_plus_strong_trend", True),
    SeasonalityFamily(26, "zero_dominated_pulse", True),
    SeasonalityFamily(27, "timing_jitter", True),
    SeasonalityFamily(41, "two_cycles", None),
    SeasonalityFamily(42, "phase_drift", None),
    SeasonalityFamily(43, "amplitude_curve", None),
)

_FAMILY_BY_NAME = {family.name: family for family in SEASONALITY_FAMILIES}


@dataclass(frozen=True)
class SeasonalityTruth:
    family: str
    family_id: int
    truth_seasonal: bool | None
    n_years: int
    replicate: int
    variant: str
    trough_month: int | None
    n_redraws: int


@dataclass(frozen=True)
class SeasonalityRecord:
    frame: pd.DataFrame
    truth: SeasonalityTruth


def _rng(family_id: int, n_years: int, replicate: int, attempt: int) -> np.random.Generator:
    return np.random.default_rng(
        np.random.SeedSequence([_BASE_ENTROPY, family_id, n_years, replicate, attempt])
    )


def _ar1(rng: np.random.Generator, n: int, coefficient: float, sd: float) -> np.ndarray:
    innovations = rng.normal(0.0, sd * np.sqrt(1.0 - coefficient**2), size=n)
    values = np.empty(n)
    values[0] = rng.normal(0.0, sd)
    for position in range(1, n):
        values[position] = coefficient * values[position - 1] + innovations[position]
    return values


def _centred_trend(n: int, total: float) -> np.ndarray:
    return total * (np.arange(n) / (n - 1) - 0.5)


def _events(rng: np.random.Generator, n: int) -> np.ndarray:
    total = n + _EVENT_BURN_IN_MONTHS
    series = np.zeros(total)
    starts = rng.random(total) < _EVENT_PROBABILITY
    for start in np.flatnonzero(starts):
        amplitude = rng.uniform(_AMPLITUDE_PCT, 2.0 * _AMPLITUDE_PCT)
        offsets = np.arange(total - start)
        series[start:] += amplitude * np.exp(-offsets / _EVENT_DECAY_MONTHS)
    expected = (
        _EVENT_PROBABILITY
        * 1.5
        * _AMPLITUDE_PCT
        / (1.0 - np.exp(-1.0 / _EVENT_DECAY_MONTHS))
    )
    return series[_EVENT_BURN_IN_MONTHS:] - expected


def _triangular_pulse(months: np.ndarray, phase: int, half_width: float) -> np.ndarray:
    offset = (months - phase + 6) % 12 - 6
    shape = np.clip(1.0 - np.abs(offset) / half_width, 0.0, None)
    return 2.0 * _AMPLITUDE_PCT * (shape - shape.mean())


def _asymmetric(months: np.ndarray, phase: int) -> np.ndarray:
    position = (months - phase) % 12
    shape = np.where(position < 3, position / 3.0, 1.0 - (position - 3) / 9.0)
    return 2.0 * _AMPLITUDE_PCT * (shape - shape.mean())


def _latent(family: str, n_years: int, rng: np.random.Generator) -> tuple[np.ndarray, int | None]:
    n = 12 * n_years
    months = np.arange(n)
    phase = int(rng.integers(12))
    noise = rng.normal(0.0, _NOISE_SD_PCT, size=n)
    annual = _AMPLITUDE_PCT * np.cos(2 * np.pi * (months - phase) / 12)
    trough_month = int((phase + 6) % 12) + 1

    if family == "white_noise":
        return _CENTRE_PCT + noise, None
    if family == "ar1_0_5":
        return _CENTRE_PCT + _ar1(rng, n, 0.5, _NOISE_SD_PCT), None
    if family == "ar1_0_8":
        return _CENTRE_PCT + _ar1(rng, n, 0.8, _NOISE_SD_PCT), None
    if family == "trend":
        return _CENTRE_PCT + _centred_trend(n, _TREND_TOTAL_PCT) + noise, None
    if family == "strong_trend":
        strong_noise = rng.normal(0.0, _STRONG_TREND_NOISE_SD_PCT, size=n)
        return _CENTRE_PCT + _centred_trend(n, _STRONG_TREND_TOTAL_PCT) + strong_noise, None
    if family == "step":
        step = np.where(months >= n // 2, _STEP_PCT, 0.0) - _STEP_PCT / 2.0
        return _CENTRE_PCT + step + noise, None
    if family == "events":
        return _CENTRE_PCT + _events(rng, n) + noise, None
    if family == "all_zero":
        return np.zeros(n), None
    if family == "sinusoid":
        return _CENTRE_PCT + annual + noise, trough_month
    if family == "narrow_pulse":
        return _CENTRE_PCT + _triangular_pulse(months, phase, 2.0) + noise, trough_month
    if family == "asymmetric":
        return _CENTRE_PCT + _asymmetric(months, phase) + noise, trough_month
    if family == "annual_plus_trend":
        return (
            _CENTRE_PCT + annual + _centred_trend(n, _TREND_TOTAL_PCT) + noise,
            trough_month,
        )
    if family == "annual_plus_strong_trend":
        strong_noise = rng.normal(0.0, _STRONG_TREND_NOISE_SD_PCT, size=n)
        values = (
            _CENTRE_PCT + annual + _centred_trend(n, _STRONG_TREND_TOTAL_PCT) + strong_noise
        )
        return values, trough_month
    if family == "zero_dominated_pulse":
        wet = np.isin((months - phase) % 12, (0, 1, 2))
        values = np.zeros(n)
        values[wet] = np.clip(
            _PULSE_LEVEL_PCT + rng.normal(0.0, _PULSE_NOISE_SD_PCT, size=int(wet.sum())),
            0.0,
            None,
        )
        return values, int((phase + 6) % 12) + 1
    if family == "timing_jitter":
        jitter = np.repeat(rng.normal(0.0, 1.0, size=n_years), 12)
        shifted = _AMPLITUDE_PCT * np.cos(2 * np.pi * (months - phase - jitter) / 12)
        return _CENTRE_PCT + shifted + noise, trough_month
    if family == "two_cycles":
        return (
            _CENTRE_PCT + _AMPLITUDE_PCT * np.cos(2 * np.pi * (months - phase) / 6) + noise,
            None,
        )
    if family == "phase_drift":
        drift = 6.0 * months / (n - 1)
        return (
            _CENTRE_PCT
            + _AMPLITUDE_PCT
            * np.cos(2 * np.pi * (months - phase - drift) / 12)
            + noise,
            None,
        )
    if family == "amplitude_curve":
        ratio = float(rng.choice([0.25, 0.5, 1.0, 2.0, 4.0]))
        scaled = ratio * _NOISE_SD_PCT * np.cos(2 * np.pi * (months - phase) / 12)
        return _CENTRE_PCT + scaled + noise, trough_month
    raise ValueError(f"unknown family {family!r}")


def _apply_variant(
    frame: pd.DataFrame, variant: str, rng: np.random.Generator, trough_month: int | None
) -> pd.DataFrame:
    out = frame.copy()
    if variant == "base":
        return out
    if variant in {"missing_10", "missing_25"}:
        fraction = 0.10 if variant == "missing_10" else 0.25
        blanked = rng.random(len(out)) < fraction
        out.loc[blanked, "extent_pct"] = np.nan
        out.loc[blanked, "invalid_pct"] = 100.0
        return out
    if variant == "low_state_gap":
        if trough_month is None:
            return out
        years = sorted({int(stamp.year) for stamp in out.index})
        for position, year in enumerate(years):
            if position % 3:
                continue
            centre = pd.Timestamp(year=year, month=trough_month, day=1)
            window = pd.date_range(centre - pd.DateOffset(months=1), periods=3, freq="MS")
            present = out.index.intersection(window)
            out.loc[present, "extent_pct"] = np.nan
            out.loc[present, "invalid_pct"] = 100.0
        return out
    if variant == "pixel_rounded":
        scaled = out["extent_pct"].astype(float) * _LOW_EXTENT_SCALE
        n_water = np.rint(scaled / 100.0 * _PIXEL_N_AOI)
        out["extent_pct"] = n_water / _PIXEL_N_AOI * 100.0
        out["n_water"] = n_water.astype("Int64")
        out["n_valid"] = _PIXEL_N_AOI
        out["n_invalid"] = 0
        out["n_aoi"] = _PIXEL_N_AOI
        return out
    raise ValueError(f"unknown variant {variant!r}")


def generate_seasonality_record(
    *,
    family: str,
    n_years: int,
    replicate: int,
    variant: str = "base",
) -> SeasonalityRecord:
    """Generate one record with its truth label, redrawing out-of-domain draws."""
    if family not in _FAMILY_BY_NAME:
        raise ValueError(f"unknown family {family!r}")
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}")
    definition = _FAMILY_BY_NAME[family]

    for attempt in range(_MAX_ATTEMPTS):
        rng = _rng(definition.family_id, n_years, replicate, attempt)
        values, trough_month = _latent(family, n_years, rng)
        if np.nanmin(values) < 0.0 or np.nanmax(values) > 100.0:
            continue
        index = pd.date_range("1990-01-01", periods=12 * n_years, freq="MS")
        frame = pd.DataFrame({"extent_pct": values, "invalid_pct": 0.0}, index=index)
        frame = _apply_variant(frame, variant, rng, trough_month)
        return SeasonalityRecord(
            frame=frame,
            truth=SeasonalityTruth(
                family=family,
                family_id=definition.family_id,
                truth_seasonal=definition.truth_seasonal,
                n_years=n_years,
                replicate=replicate,
                variant=variant,
                trough_month=trough_month,
                n_redraws=attempt,
            ),
        )
    raise RuntimeError(f"{family} could not be drawn inside 0-100% in {_MAX_ATTEMPTS} attempts")


def iter_seasonality_records(
    *,
    lengths: tuple[int, ...] = (7, 15, 30),
    replicates: int = 200,
    variants: tuple[str, ...] = ("base",),
) -> Iterator[SeasonalityRecord]:
    """Yield every family x length x replicate x variant record, in a fixed order."""
    for variant in variants:
        for definition in SEASONALITY_FAMILIES:
            for n_years in lengths:
                for replicate in range(replicates):
                    yield generate_seasonality_record(
                        family=definition.name,
                        n_years=n_years,
                        replicate=replicate,
                        variant=variant,
                    )
