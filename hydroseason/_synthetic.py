"""Synthetic records with known truth, for calibration and validation.

Two partitions with disjoint seed ranges. The calibration partition is where
thresholds are chosen; the validation partition is run once, after constants
are frozen, and never informs a threshold.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

import numpy as np
import pandas as pd

CALIBRATION_SEEDS = range(10000, 15000)
VALIDATION_SEEDS = range(20000, 25000)

_RECORD_LENGTHS = (5, 7, 10, 20, 30)

_CALIBRATION_FAMILIES = (
    "unimodal_symmetric", "unimodal_asymmetric", "monsoonal_sharp", "wet_plateau",
    "bimodal", "switching_modes", "phase_drift", "amplitude_drift",
    "flatline", "near_flat_noise", "white_noise", "autocorrelated_noise",
    "random_walk", "monotonic_trend", "event_pulses", "multi_year_regimes",
    "tied_low_plateau",
)
_VALIDATION_FAMILIES = _CALIBRATION_FAMILIES + (
    "triangular", "skewed_pulse", "compound_pulse", "step_change",
)

_ANNUAL_FAMILIES = frozenset({
    "unimodal_symmetric", "unimodal_asymmetric", "monsoonal_sharp", "wet_plateau",
    "phase_drift", "amplitude_drift", "triangular", "skewed_pulse", "tied_low_plateau",
})


@dataclass(frozen=True)
class TruthLabels:
    is_annual: bool
    trough_month: int | None
    peak_month: int | None
    phase_by_month: pd.Series | None
    n_years: int


@dataclass(frozen=True)
class ScenarioMetadata:
    missingness: str
    quality_loss: str
    noise_pp: float
    timing_jitter_months: int
    bias_strength_pp: float


@dataclass(frozen=True)
class SyntheticRecord:
    frame: pd.DataFrame
    truth: TruthLabels
    scenario: ScenarioMetadata
    family: str
    seed: int


@dataclass(frozen=True)
class _LatentResult:
    values: np.ndarray
    trough_by_year: np.ndarray
    phase_by_month: pd.Series | None


def apply_extent_dependent_bias(extent: pd.Series, *, strength_pp: float) -> pd.Series:
    """Subtract a one-sided offset that grows as true extent falls.

    Published validation of Landsat water classification over eastern Australia
    reports 95-99% overall accuracy on pure water pixels against 73-75% on
    mixed pixels, with omission exceeding commission and area underestimated
    for small bodies and long perimeters. Low-extent months are therefore
    biased low, not merely noisier.

    This is deliberately NOT the quality-degradation family. That one lowers a
    month's weight; this one shifts its value. Only the second inflates
    seasonal amplitude, and only for the low-extent catchments whose annual
    cycle is least resolved.
    """
    if strength_pp < 0.0:
        raise ValueError("strength_pp must be non-negative.")
    if strength_pp == 0.0:
        return extent.copy()
    values = extent.to_numpy(dtype=float)
    # Weight rises smoothly as extent falls; halves by ~20 pp of extent.
    weight = np.exp(-np.clip(values, 0.0, None) / 20.0)
    return pd.Series(np.clip(values - strength_pp * weight, 0.0, 100.0), index=extent.index)


def _monthly_index(n_years: int) -> pd.DatetimeIndex:
    return pd.date_range("1990-01-01", periods=12 * n_years, freq="MS")


def _u_coord(months: np.ndarray, trough_month: float) -> np.ndarray:
    """Compute circular [0, 1) phase coordinate relative to trough month."""
    return ((months - trough_month) % 12.0) / 12.0


def _derive_annual_phases(
    index: pd.DatetimeIndex,
    values: np.ndarray,
    trough_months: np.ndarray,
) -> pd.Series:
    """Derive 4-phase labels ('dry', 'recovery', 'wet', 'recession') per cycle."""
    n_months = len(index)
    n_years = n_months // 12
    phases = np.empty(n_months, dtype=object)

    for y in range(n_years):
        sl = slice(y * 12, (y + 1) * 12)
        y_val = values[sl]
        v_min = np.min(y_val)
        v_max = np.max(y_val)
        span = v_max - v_min
        if span <= 1e-6:
            phases[sl] = "dry"
            continue

        z = (y_val - v_min) / span
        pk_idx = int(np.argmax(z))

        # Classify each month in the year based on normalized height and rise/fall limb
        for m_idx in range(12):
            val_z = z[m_idx]
            if m_idx <= pk_idx:
                # Rising limb (trough -> peak)
                if val_z < 0.25:
                    phases[y * 12 + m_idx] = "dry"
                elif val_z <= 0.75:
                    phases[y * 12 + m_idx] = "recovery"
                else:
                    phases[y * 12 + m_idx] = "wet"
            else:
                # Falling limb (peak -> trough)
                if val_z > 0.75:
                    phases[y * 12 + m_idx] = "wet"
                elif val_z >= 0.25:
                    phases[y * 12 + m_idx] = "recession"
                else:
                    phases[y * 12 + m_idx] = "dry"

    return pd.Series(phases, index=index, dtype=object)


# Waveform builders
def _build_unimodal_symmetric(
    index: pd.DatetimeIndex, trough_month: int, amplitude: float, mean: float, rng: np.random.Generator
) -> _LatentResult:
    months = index.month.to_numpy()
    u = _u_coord(months, trough_month)
    values = mean - 0.5 * amplitude * np.cos(2.0 * np.pi * u)
    n_years = len(index) // 12
    troughs = np.full(n_years, trough_month, dtype=int)
    phase_series = _derive_annual_phases(index, values, troughs)
    return _LatentResult(values=values, trough_by_year=troughs, phase_by_month=phase_series)


def _build_unimodal_asymmetric(
    index: pd.DatetimeIndex, trough_month: int, amplitude: float, mean: float, rng: np.random.Generator
) -> _LatentResult:
    months = index.month.to_numpy()
    u = _u_coord(months, trough_month)
    values = mean - 0.5 * amplitude * np.cos(2.0 * np.pi * u) + 0.20 * amplitude * np.sin(4.0 * np.pi * u)
    n_years = len(index) // 12
    troughs = np.full(n_years, trough_month, dtype=int)
    phase_series = _derive_annual_phases(index, values, troughs)
    return _LatentResult(values=values, trough_by_year=troughs, phase_by_month=phase_series)


def _build_monsoonal_sharp(
    index: pd.DatetimeIndex, trough_month: int, amplitude: float, mean: float, rng: np.random.Generator
) -> _LatentResult:
    months = index.month.to_numpy()
    u = _u_coord(months, trough_month)
    shape = (1.0 - np.cos(2.0 * np.pi * u)) / 2.0
    values = mean + amplitude * (shape**3.0) - 0.5 * amplitude
    n_years = len(index) // 12
    troughs = np.full(n_years, trough_month, dtype=int)
    phase_series = _derive_annual_phases(index, values, troughs)
    return _LatentResult(values=values, trough_by_year=troughs, phase_by_month=phase_series)


def _build_wet_plateau(
    index: pd.DatetimeIndex, trough_month: int, amplitude: float, mean: float, rng: np.random.Generator
) -> _LatentResult:
    months = index.month.to_numpy()
    u = _u_coord(months, trough_month)
    raw = mean - 0.5 * amplitude * np.cos(2.0 * np.pi * u)
    p65 = float(np.percentile(raw, 65.0))
    values = np.minimum(raw, p65)
    n_years = len(index) // 12
    troughs = np.full(n_years, trough_month, dtype=int)
    phase_series = _derive_annual_phases(index, values, troughs)
    return _LatentResult(values=values, trough_by_year=troughs, phase_by_month=phase_series)


def _build_bimodal(
    index: pd.DatetimeIndex, trough_month: int, amplitude: float, mean: float, rng: np.random.Generator
) -> _LatentResult:
    months = index.month.to_numpy()
    u = _u_coord(months, trough_month)
    values = mean - 0.35 * amplitude * np.cos(4.0 * np.pi * u)
    n_years = len(index) // 12
    troughs = np.full(n_years, trough_month, dtype=int)
    return _LatentResult(values=values, trough_by_year=troughs, phase_by_month=None)


def _build_switching_modes(
    index: pd.DatetimeIndex, trough_month: int, amplitude: float, mean: float, rng: np.random.Generator
) -> _LatentResult:
    n_months = len(index)
    n_years = n_months // 12
    values = np.empty(n_months, dtype=float)
    troughs = np.empty(n_years, dtype=int)
    for y in range(n_years):
        t_y = ((trough_month + 6 - 1) % 12) + 1 if (y % 2 == 1) else trough_month
        troughs[y] = t_y
        m = index[y * 12 : (y + 1) * 12].month.to_numpy()
        u = _u_coord(m, t_y)
        values[y * 12 : (y + 1) * 12] = mean - 0.5 * amplitude * np.cos(2.0 * np.pi * u)
    return _LatentResult(values=values, trough_by_year=troughs, phase_by_month=None)


def _build_phase_drift(
    index: pd.DatetimeIndex, trough_month: int, amplitude: float, mean: float, rng: np.random.Generator
) -> _LatentResult:
    n_months = len(index)
    n_years = n_months // 12
    drift = np.linspace(-2.0, 2.0, n_months)
    months = index.month.to_numpy()
    u = ((months - (trough_month + drift)) % 12.0) / 12.0
    values = mean - 0.5 * amplitude * np.cos(2.0 * np.pi * u)
    troughs = np.array([int(np.round(((trough_month + drift[y * 12 + 6] - 1) % 12) + 1)) for y in range(n_years)])
    phase_series = _derive_annual_phases(index, values, troughs)
    return _LatentResult(values=values, trough_by_year=troughs, phase_by_month=phase_series)


def _build_amplitude_drift(
    index: pd.DatetimeIndex, trough_month: int, amplitude: float, mean: float, rng: np.random.Generator
) -> _LatentResult:
    n_months = len(index)
    n_years = n_months // 12
    scale = np.linspace(0.5, 1.5, n_months)
    months = index.month.to_numpy()
    u = _u_coord(months, trough_month)
    values = mean - 0.5 * (amplitude * scale) * np.cos(2.0 * np.pi * u)
    troughs = np.full(n_years, trough_month, dtype=int)
    phase_series = _derive_annual_phases(index, values, troughs)
    return _LatentResult(values=values, trough_by_year=troughs, phase_by_month=phase_series)


def _build_flatline(
    index: pd.DatetimeIndex, trough_month: int, amplitude: float, mean: float, rng: np.random.Generator
) -> _LatentResult:
    values = np.full(len(index), mean, dtype=float)
    n_years = len(index) // 12
    troughs = np.full(n_years, trough_month, dtype=int)
    return _LatentResult(values=values, trough_by_year=troughs, phase_by_month=None)


def _build_near_flat_noise(
    index: pd.DatetimeIndex, trough_month: int, amplitude: float, mean: float, rng: np.random.Generator
) -> _LatentResult:
    values = np.full(len(index), mean, dtype=float)
    n_years = len(index) // 12
    troughs = np.full(n_years, trough_month, dtype=int)
    return _LatentResult(values=values, trough_by_year=troughs, phase_by_month=None)


def _build_white_noise(
    index: pd.DatetimeIndex, trough_month: int, amplitude: float, mean: float, rng: np.random.Generator
) -> _LatentResult:
    values = rng.uniform(10.0, 80.0, size=len(index))
    n_years = len(index) // 12
    troughs = np.full(n_years, trough_month, dtype=int)
    return _LatentResult(values=values, trough_by_year=troughs, phase_by_month=None)


def _build_autocorrelated_noise(
    index: pd.DatetimeIndex, trough_month: int, amplitude: float, mean: float, rng: np.random.Generator
) -> _LatentResult:
    n_months = len(index)
    phi = 0.8
    sigma = rng.uniform(2.0, 8.0)
    innovations = rng.normal(0.0, sigma, size=n_months)
    values = np.empty(n_months, dtype=float)
    values[0] = mean + innovations[0]
    for i in range(1, n_months):
        values[i] = mean + phi * (values[i - 1] - mean) + innovations[i]
    n_years = n_months // 12
    troughs = np.full(n_years, trough_month, dtype=int)
    return _LatentResult(values=np.clip(values, 0.0, 100.0), trough_by_year=troughs, phase_by_month=None)


def _build_random_walk(
    index: pd.DatetimeIndex, trough_month: int, amplitude: float, mean: float, rng: np.random.Generator
) -> _LatentResult:
    innovations = rng.normal(0.0, 2.5, size=len(index))
    values = mean + np.cumsum(innovations)
    n_years = len(index) // 12
    troughs = np.full(n_years, trough_month, dtype=int)
    return _LatentResult(values=np.clip(values, 0.0, 100.0), trough_by_year=troughs, phase_by_month=None)


def _build_monotonic_trend(
    index: pd.DatetimeIndex, trough_month: int, amplitude: float, mean: float, rng: np.random.Generator
) -> _LatentResult:
    start_v = rng.uniform(10.0, 90.0)
    end_v = rng.uniform(10.0, 90.0)
    values = np.linspace(start_v, end_v, len(index))
    n_years = len(index) // 12
    troughs = np.full(n_years, trough_month, dtype=int)
    return _LatentResult(values=values, trough_by_year=troughs, phase_by_month=None)


def _build_event_pulses(
    index: pd.DatetimeIndex, trough_month: int, amplitude: float, mean: float, rng: np.random.Generator
) -> _LatentResult:
    n_months = len(index)
    values = np.full(n_months, mean, dtype=float)
    n_pulses = rng.integers(1, 5)
    for _ in range(n_pulses):
        loc = rng.integers(0, n_months)
        height = rng.uniform(0.5 * amplitude, 1.5 * amplitude)
        width = rng.integers(1, 4)
        for d in range(-width, width + 1):
            if 0 <= loc + d < n_months:
                values[loc + d] += height * np.exp(-0.5 * (d / max(width * 0.5, 0.5)) ** 2)
    n_years = n_months // 12
    troughs = np.full(n_years, trough_month, dtype=int)
    return _LatentResult(values=np.clip(values, 0.0, 100.0), trough_by_year=troughs, phase_by_month=None)


def _build_multi_year_regimes(
    index: pd.DatetimeIndex, trough_month: int, amplitude: float, mean: float, rng: np.random.Generator
) -> _LatentResult:
    n_months = len(index)
    n_years = n_months // 12
    values = np.empty(n_months, dtype=float)
    cur_y = 0
    while cur_y < n_years:
        block_len = min(rng.integers(2, 6), n_years - cur_y)
        lvl = rng.uniform(15.0, 85.0)
        values[cur_y * 12 : (cur_y + block_len) * 12] = lvl
        cur_y += block_len
    troughs = np.full(n_years, trough_month, dtype=int)
    return _LatentResult(values=values, trough_by_year=troughs, phase_by_month=None)


def _build_tied_low_plateau(
    index: pd.DatetimeIndex, trough_month: int, amplitude: float, mean: float, rng: np.random.Generator
) -> _LatentResult:
    months = index.month.to_numpy()
    u = _u_coord(months, trough_month)
    raw = mean - 0.5 * amplitude * np.cos(2.0 * np.pi * u)
    p25 = float(np.percentile(raw, 25.0))
    values = np.maximum(raw, p25)
    n_years = len(index) // 12
    troughs = np.full(n_years, trough_month, dtype=int)
    phase_series = _derive_annual_phases(index, values, troughs)
    return _LatentResult(values=values, trough_by_year=troughs, phase_by_month=phase_series)


def _build_triangular(
    index: pd.DatetimeIndex, trough_month: int, amplitude: float, mean: float, rng: np.random.Generator
) -> _LatentResult:
    months = index.month.to_numpy()
    u = _u_coord(months, trough_month)  # [0, 1)
    shape = 1.0 - 2.0 * np.abs(u - 0.5)  # 0 at trough (0 & 1), 1 at peak (0.5)
    values = mean + amplitude * (shape - 0.5)
    n_years = len(index) // 12
    troughs = np.full(n_years, trough_month, dtype=int)
    phase_series = _derive_annual_phases(index, values, troughs)
    return _LatentResult(values=values, trough_by_year=troughs, phase_by_month=phase_series)


def _build_skewed_pulse(
    index: pd.DatetimeIndex, trough_month: int, amplitude: float, mean: float, rng: np.random.Generator
) -> _LatentResult:
    months = index.month.to_numpy()
    u = _u_coord(months, trough_month)  # [0, 1)
    # Piecewise linear: 3-month rise (u in 0..0.25) and 9-month fall (u in 0.25..1.0)
    shape = np.where(u < 0.25, u / 0.25, (1.0 - u) / 0.75)
    values = mean + amplitude * (shape - 0.5)
    n_years = len(index) // 12
    troughs = np.full(n_years, trough_month, dtype=int)
    phase_series = _derive_annual_phases(index, values, troughs)
    return _LatentResult(values=values, trough_by_year=troughs, phase_by_month=phase_series)


def _build_compound_pulse(
    index: pd.DatetimeIndex, trough_month: int, amplitude: float, mean: float, rng: np.random.Generator
) -> _LatentResult:
    months = index.month.to_numpy()
    u = _u_coord(months, trough_month)
    # Two unequal pulses separated by 4 months
    p1 = np.exp(-0.5 * (((u - 0.3) % 1.0) / 0.08) ** 2)
    p2 = 0.6 * np.exp(-0.5 * (((u - 0.65) % 1.0) / 0.08) ** 2)
    shape = p1 + p2
    values = mean + amplitude * (shape - 0.5)
    n_years = len(index) // 12
    troughs = np.full(n_years, trough_month, dtype=int)
    return _LatentResult(values=values, trough_by_year=troughs, phase_by_month=None)


def _build_step_change(
    index: pd.DatetimeIndex, trough_month: int, amplitude: float, mean: float, rng: np.random.Generator
) -> _LatentResult:
    n_months = len(index)
    mid = n_months // 2
    step = rng.uniform(15.0, 35.0) * (1.0 if rng.random() > 0.5 else -1.0)
    values = np.full(n_months, mean, dtype=float)
    values[mid:] += step
    n_years = n_months // 12
    troughs = np.full(n_years, trough_month, dtype=int)
    return _LatentResult(values=np.clip(values, 0.0, 100.0), trough_by_year=troughs, phase_by_month=None)


_WAVEFORM_BUILDERS: dict[str, Callable[[pd.DatetimeIndex, int, float, float, np.random.Generator], _LatentResult]] = {
    "unimodal_symmetric": _build_unimodal_symmetric,
    "unimodal_asymmetric": _build_unimodal_asymmetric,
    "monsoonal_sharp": _build_monsoonal_sharp,
    "wet_plateau": _build_wet_plateau,
    "bimodal": _build_bimodal,
    "switching_modes": _build_switching_modes,
    "phase_drift": _build_phase_drift,
    "amplitude_drift": _build_amplitude_drift,
    "flatline": _build_flatline,
    "near_flat_noise": _build_near_flat_noise,
    "white_noise": _build_white_noise,
    "autocorrelated_noise": _build_autocorrelated_noise,
    "random_walk": _build_random_walk,
    "monotonic_trend": _build_monotonic_trend,
    "event_pulses": _build_event_pulses,
    "multi_year_regimes": _build_multi_year_regimes,
    "tied_low_plateau": _build_tied_low_plateau,
    "triangular": _build_triangular,
    "skewed_pulse": _build_skewed_pulse,
    "compound_pulse": _build_compound_pulse,
    "step_change": _build_step_change,
}


def apply_observation_scenario(
    latent_values: np.ndarray,
    trough_by_year: np.ndarray,
    *,
    scenario: ScenarioMetadata,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray]:
    """Apply degradation scenario in order: jitter, noise, missingness, quality loss, bias."""
    n_months = len(latent_values)
    values = latent_values.copy()

    # 1. Timing jitter
    if scenario.timing_jitter_months > 0:
        n_years = n_months // 12
        jittered = np.empty_like(values)
        for y in range(n_years):
            sl = slice(y * 12, (y + 1) * 12)
            shift = int(rng.integers(-scenario.timing_jitter_months, scenario.timing_jitter_months + 1))
            jittered[sl] = np.roll(values[sl], shift)
        values = jittered

    # 2. Additive noise
    if scenario.noise_pp > 0:
        values += rng.normal(0.0, scenario.noise_pp, size=n_months)

    # 3. Missingness
    if scenario.missingness == "random":
        mask = rng.random(size=n_months) < 0.05
        values[mask] = np.nan
    elif scenario.missingness == "seasonal":
        # Missingness concentrated in wet months / peak season
        n_years = n_months // 12
        for y in range(n_years):
            t_m = trough_by_year[y]
            peak_m = ((t_m + 5) % 12) + 1
            for m in range(12):
                cal_month = m + 1
                dist = min(abs(cal_month - peak_m), 12 - abs(cal_month - peak_m))
                prob = 0.20 if dist <= 1 else 0.02
                if rng.random() < prob:
                    values[y * 12 + m] = np.nan

    # 4. Quality loss (invalid_pct)
    invalid = np.zeros(n_months, dtype=float)
    if scenario.quality_loss == "extrema":
        n_years = n_months // 12
        for y in range(n_years):
            t_m = trough_by_year[y]
            peak_m = ((t_m + 5) % 12) + 1
            for m in range(12):
                cal_month = m + 1
                dist_pk = min(abs(cal_month - peak_m), 12 - abs(cal_month - peak_m))
                dist_tr = min(abs(cal_month - t_m), 12 - abs(cal_month - t_m))
                if dist_pk <= 1 or dist_tr <= 1:
                    invalid[y * 12 + m] = float(rng.uniform(30.0, 60.0))
                else:
                    invalid[y * 12 + m] = float(rng.uniform(0.0, 10.0))
    else:
        invalid = rng.uniform(0.0, 5.0, size=n_months)

    # 5. One-sided extent-dependent bias
    if scenario.bias_strength_pp > 0.0:
        s = pd.Series(values)
        values = apply_extent_dependent_bias(s, strength_pp=scenario.bias_strength_pp).to_numpy()

    return values, invalid


def generate_record(seed: int, *, partition: Literal["calibration", "validation"]) -> SyntheticRecord:
    """Deterministically generate one labelled synthetic record."""
    if partition not in {"calibration", "validation"}:
        raise ValueError("partition must be 'calibration' or 'validation'.")
    valid = CALIBRATION_SEEDS if partition == "calibration" else VALIDATION_SEEDS
    if seed not in valid:
        raise ValueError(f"seed {seed} is outside the {partition} partition.")

    rng = np.random.default_rng(seed)
    families = _CALIBRATION_FAMILIES if partition == "calibration" else _VALIDATION_FAMILIES
    family = families[seed % len(families)]
    n_years = _RECORD_LENGTHS[rng.integers(0, len(_RECORD_LENGTHS))]
    index = _monthly_index(n_years)

    trough_month = int(rng.integers(1, 13))
    amplitude = float(rng.uniform(5.0, 60.0))
    mean = float(rng.uniform(20.0, 70.0))
    latent = _WAVEFORM_BUILDERS[family](
        index=index,
        trough_month=trough_month,
        amplitude=amplitude,
        mean=mean,
        rng=rng,
    )
    scenario = ScenarioMetadata(
        missingness=("none", "random", "seasonal")[seed % 3],
        quality_loss=("none", "extrema")[seed % 2],
        noise_pp=float((0.5, 2.0, 5.0, 8.0)[seed % 4]),
        timing_jitter_months=int((0, 1, 2)[seed % 3]),
        bias_strength_pp=float((0.0, 1.0, 2.0, 4.0, 8.0)[seed % 5]),
    )
    values, invalid = apply_observation_scenario(
        latent.values,
        latent.trough_by_year,
        scenario=scenario,
        rng=rng,
    )

    frame = pd.DataFrame(
        {"extent_pct": np.clip(values, 0.0, 100.0), "invalid_pct": invalid},
        index=index,
    )
    truth = TruthLabels(
        is_annual=family in _ANNUAL_FAMILIES,
        trough_month=trough_month if family in _ANNUAL_FAMILIES else None,
        peak_month=((trough_month + 5) % 12) + 1 if family in _ANNUAL_FAMILIES else None,
        phase_by_month=latent.phase_by_month,
        n_years=n_years,
    )
    return SyntheticRecord(
        frame=frame, truth=truth, scenario=scenario, family=family, seed=seed
    )
