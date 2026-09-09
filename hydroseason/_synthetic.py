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
    trough_month_by_year: tuple[int, ...]


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
        peak_month = int(index[sl][int(np.argmax(z))].month)
        trough_month = int(trough_months[y])
        peak_position = (peak_month - trough_month) % 12

        # Classify relative to trough-to-trough cycle, including calendar wrap.
        for m_idx in range(12):
            val_z = z[m_idx]
            month = int(index[y * 12 + m_idx].month)
            cycle_position = (month - trough_month) % 12
            if cycle_position <= peak_position:
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


def _scenario_for_seed(seed: int) -> ScenarioMetadata:
    """Draw independent degradation axes from a seed-isolated RNG stream."""
    rng = np.random.default_rng(np.random.SeedSequence([int(seed), 0x48594452]))
    return ScenarioMetadata(
        missingness=("none", "random", "seasonal")[int(rng.integers(0, 3))],
        quality_loss=("none", "extrema")[int(rng.integers(0, 2))],
        noise_pp=float((0.5, 2.0, 5.0, 8.0)[int(rng.integers(0, 4))]),
        timing_jitter_months=int(rng.integers(0, 3)),
        bias_strength_pp=float(
            (0.0, 1.0, 2.0, 4.0, 8.0)[int(rng.integers(0, 5))]
        ),
    )


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
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Apply degradation scenario in order: jitter, noise, missingness, quality loss, bias."""
    n_months = len(latent_values)
    values = latent_values.copy()
    n_years = n_months // 12
    timing_shifts = np.zeros(n_years, dtype=int)

    # 1. Timing jitter
    if scenario.timing_jitter_months > 0:
        jittered = np.empty_like(values)
        for y in range(n_years):
            sl = slice(y * 12, (y + 1) * 12)
            shift = int(rng.integers(-scenario.timing_jitter_months, scenario.timing_jitter_months + 1))
            timing_shifts[y] = shift
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

    return values, invalid, timing_shifts


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
    scenario = _scenario_for_seed(seed)
    values, invalid, timing_shifts = apply_observation_scenario(
        latent.values,
        latent.trough_by_year,
        scenario=scenario,
        rng=rng,
    )

    frame = pd.DataFrame(
        {"extent_pct": np.clip(values, 0.0, 100.0), "invalid_pct": invalid},
        index=index,
    )
    truth_troughs = (
        (latent.trough_by_year.astype(int) - 1 + timing_shifts) % 12 + 1
    ).astype(int)
    truth_phases = latent.phase_by_month
    if truth_phases is not None and np.any(timing_shifts):
        adjusted = truth_phases.to_numpy(dtype=object).copy()
        for year_index, shift in enumerate(timing_shifts):
            sl = slice(year_index * 12, (year_index + 1) * 12)
            adjusted[sl] = np.roll(adjusted[sl], int(shift))
        truth_phases = pd.Series(adjusted, index=truth_phases.index, dtype=object)

    truth = TruthLabels(
        is_annual=family in _ANNUAL_FAMILIES,
        trough_month=trough_month if family in _ANNUAL_FAMILIES else None,
        peak_month=((trough_month + 5) % 12) + 1 if family in _ANNUAL_FAMILIES else None,
        phase_by_month=truth_phases,
        n_years=n_years,
        trough_month_by_year=tuple(int(month) for month in truth_troughs),
    )
    return SyntheticRecord(
        frame=frame, truth=truth, scenario=scenario, family=family, seed=seed
    )


# TIMING_IDENTIFIABILITY_SYNTHETIC_CORPUS
#
# Keep this corpus independent of ``generate_record``.  The legacy generator
# underpins the shipped evidence calibration; adding a timing-specific family
# must not perturb its family allocation or invalidate its frozen artifact.


@dataclass(frozen=True)
class TimingTruthLabels:
    """Known annual timing support for the zero-dominated timing corpus."""

    is_annual: bool
    trough_month: int | None
    peak_month: int | None
    phase_by_month: pd.Series | None
    n_years: int
    trough_month_by_year: tuple[int, ...]
    detectable_peak_by_year: tuple[bool, ...]
    detectable_trough_by_year: tuple[bool, ...]
    peak_months_by_year: tuple[tuple[int, ...], ...]
    trough_months_by_year: tuple[tuple[int, ...], ...]


_TIMING_IDENTIFIABILITY_FAMILIES = (
    "all_zero_years",
    "broad_zero_plateaus",
    "one_pixel_pulses",
    "intermittent_seasonal_pulses",
    "intermittent_aseasonal_pulses",
    "persistent_low_amplitude_water",
    "variable_valid_pixel_counts",
    "cloud_gaps",
)


def _timing_counts_frame(
    index: pd.DatetimeIndex, values: np.ndarray, *, valid: np.ndarray, cloud: np.ndarray
) -> pd.DataFrame:
    n_aoi = np.full(len(index), 100, dtype=int)
    n_valid = np.where(cloud, 0, np.asarray(valid, dtype=int))
    n_invalid = n_aoi - n_valid
    n_water = np.rint(np.clip(values, 0.0, 100.0) * n_valid / 100.0).astype(int)
    return pd.DataFrame(
        {
            "n_water": n_water,
            "n_valid": n_valid,
            "n_invalid": n_invalid,
            "n_aoi": n_aoi,
        },
        index=index,
    )


def generate_timing_identifiability_record(
    seed: int, *, partition: Literal["calibration", "validation"]
) -> SyntheticRecord:
    """Build one deterministic, truth-labelled record for timing calibration.

    These families deliberately exercise the independent annual metrics from
    :mod:`hydroseason._timing_identifiability`; no station, rainfall, policy,
    or motivating-record output enters this corpus.
    """
    if partition not in {"calibration", "validation"}:
        raise ValueError("partition must be 'calibration' or 'validation'.")
    valid_seeds = CALIBRATION_SEEDS if partition == "calibration" else VALIDATION_SEEDS
    if seed not in valid_seeds:
        raise ValueError(f"seed {seed} is outside the {partition} partition.")

    rng = np.random.default_rng(np.random.SeedSequence([int(seed), 0x54494D45]))
    family = _TIMING_IDENTIFIABILITY_FAMILIES[seed % len(_TIMING_IDENTIFIABILITY_FAMILIES)]
    n_years = 10
    index = _monthly_index(n_years)
    months = index.month.to_numpy()
    peak_month, trough_month = 8, 2
    peak_set = (peak_month,)
    trough_set = (trough_month,)
    values = np.full(len(index), 10.0, dtype=float)
    valid = np.full(len(index), 100, dtype=int)
    cloud = np.zeros(len(index), dtype=bool)
    peak_detectable = np.ones(n_years, dtype=bool)
    trough_detectable = np.ones(n_years, dtype=bool)
    peak_intervals = [peak_set for _ in range(n_years)]
    trough_intervals = [trough_set for _ in range(n_years)]
    annual = True

    for year in range(n_years):
        rows = np.arange(year * 12, (year + 1) * 12)
        values[rows] = 10.0
        values[rows[months[rows] == trough_month]] = 1.0
        values[rows[months[rows] == peak_month]] = 50.0

    if family == "all_zero_years":
        values[:] = 0.0
        annual = False
        peak_detectable[:] = trough_detectable[:] = False
        peak_intervals = trough_intervals = [() for _ in range(n_years)]
    elif family == "broad_zero_plateaus":
        values[:] = 0.0
        values[np.isin(months, [7, 8, 9])] = 25.0
        annual = False
        peak_detectable[:] = trough_detectable[:] = False
        peak_intervals = [(7, 8, 9) for _ in range(n_years)]
        trough_intervals = [(10, 11, 12, 1, 2, 3, 4, 5, 6) for _ in range(n_years)]
    elif family == "one_pixel_pulses":
        values[:] = 0.0
        values[months == peak_month] = 1.0
        annual = False
        peak_detectable[:] = trough_detectable[:] = False
        peak_intervals = [peak_set for _ in range(n_years)]
        trough_intervals = [(1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12) for _ in range(n_years)]
    elif family == "intermittent_seasonal_pulses":
        for year in range(n_years):
            if year in {1, 4, 8}:
                rows = np.arange(year * 12, (year + 1) * 12)
                values[rows] = 0.0
                peak_detectable[year] = trough_detectable[year] = False
                peak_intervals[year] = trough_intervals[year] = ()
    elif family == "intermittent_aseasonal_pulses":
        values[:] = 0.0
        for year in range(n_years):
            month = int(rng.integers(1, 13))
            values[year * 12 + month - 1] = 1.0
        annual = False
        peak_detectable[:] = trough_detectable[:] = False
        peak_intervals = trough_intervals = [() for _ in range(n_years)]
    elif family == "persistent_low_amplitude_water":
        values[:] = 30.0
        values[months == trough_month] = 29.5
        values[months == peak_month] = 30.5
        annual = False
        peak_detectable[:] = trough_detectable[:] = False
        peak_intervals = trough_intervals = [() for _ in range(n_years)]
    elif family == "variable_valid_pixel_counts":
        valid = np.where(np.isin(months, [peak_month, trough_month]), 25, 100)
    elif family == "cloud_gaps":
        for year in range(n_years):
            if year in {0, 3, 6, 9}:
                rows = np.arange(year * 12, (year + 1) * 12)
                cloud[rows[months[rows] == peak_month]] = True
                peak_detectable[year] = False
                peak_intervals[year] = ()

    frame = _timing_counts_frame(index, values, valid=valid, cloud=cloud)
    truth = TimingTruthLabels(
        is_annual=annual,
        trough_month=trough_month if annual else None,
        peak_month=peak_month if annual else None,
        phase_by_month=None,
        n_years=n_years,
        trough_month_by_year=tuple([trough_month] * n_years),
        detectable_peak_by_year=tuple(bool(item) for item in peak_detectable),
        detectable_trough_by_year=tuple(bool(item) for item in trough_detectable),
        peak_months_by_year=tuple(peak_intervals),
        trough_months_by_year=tuple(trough_intervals),
    )
    scenario = ScenarioMetadata("none", "none", 0.0, 0, 0.0)
    return SyntheticRecord(frame=frame, truth=truth, scenario=scenario, family=family, seed=seed)


# ---------------------------------------------------------------------------
# Trough search geometry corpus
#
# Kept independent of ``generate_record`` and
# ``generate_timing_identifiability_record``: both underpin frozen calibration
# artifacts, and adding a family to either would change its allocation and
# invalidate its fingerprint.  Seed ranges are disjoint from both.
# ---------------------------------------------------------------------------

GEOMETRY_CALIBRATION_SEEDS = range(30000, 35000)
GEOMETRY_VALIDATION_SEEDS = range(40000, 45000)

_TROUGH_GEOMETRY_FAMILIES = (
    "stationary_trough",
    "wide_phase_excursion",
    "abrupt_phase_shift",
    "competing_secondary_minimum",
    "tied_low_plateau_wide",
    "missing_outer_months",
    "quality_loss_outer_months",
    "zero_dominated_wide_excursion",
    "short_cycle_stress",
    "long_cycle_stress",
)

_GEOMETRY_N_YEARS = 12
_GEOMETRY_ANCHOR_MONTH = 7
_GEOMETRY_BASE_PP = 40.0
_GEOMETRY_TROUGH_PP = 2.0
_GEOMETRY_PEAK_PP = 70.0
# Must match ``_monthly_index``, which starts at 1990.  A truth date built on a
# different base year silently falls outside the frame and every boundary-error
# metric computed against it is meaningless.
_GEOMETRY_BASE_YEAR = 1990


@dataclass(frozen=True)
class TroughGeometryTruthLabels:
    """Known trough position per year for the search-geometry corpus.

    ``trough_date_by_year`` is ``None`` for a year with no identifiable point
    trough -- a broad equivalent-low plateau or a fully masked year.  For those
    years abstention is the correct answer and a published point date is a
    false precise boundary.
    """

    climatological_trough_month: int
    n_years: int
    trough_date_by_year: tuple[pd.Timestamp | None, ...]
    identifiable_by_year: tuple[bool, ...]
    max_abs_excursion_months: int


def _geometry_month(year_offset: int, month: int) -> pd.Timestamp:
    """Month-start timestamp for a calendar month inside one corpus year."""
    return pd.Timestamp(_GEOMETRY_BASE_YEAR + year_offset, month, 1)


def _geometry_frame(
    index: pd.DatetimeIndex,
    values: np.ndarray,
    *,
    valid: np.ndarray,
    masked: np.ndarray,
) -> pd.DataFrame:
    """Counts plus the percentages the detector reads.

    ``extent_pct`` is written explicitly rather than left to
    ``prepare_monthly_extent`` so the corpus is readable in isolation and a
    masked month is unambiguously missing rather than zero water.
    """
    n_aoi = np.full(len(index), 100, dtype=int)
    n_valid = np.where(masked, 0, np.asarray(valid, dtype=int))
    n_invalid = n_aoi - n_valid
    n_water = np.rint(np.clip(values, 0.0, 100.0) * n_valid / 100.0).astype(int)
    with np.errstate(invalid="ignore", divide="ignore"):
        extent_pct = np.where(n_valid > 0, 100.0 * n_water / n_valid, np.nan)
    return pd.DataFrame(
        {
            "n_water": n_water,
            "n_valid": n_valid,
            "n_invalid": n_invalid,
            "n_aoi": n_aoi,
            "extent_pct": extent_pct,
            "invalid_pct": 100.0 * n_invalid / n_aoi,
        },
        index=index,
    )


def _geometry_shifted_month(anchor: int, shift: int) -> int:
    """Calendar month ``shift`` months from ``anchor``, wrapping the year."""
    return ((anchor - 1 + shift) % 12) + 1


def generate_trough_geometry_record(
    seed: int, *, partition: Literal["calibration", "validation"]
) -> SyntheticRecord:
    """Build one deterministic, truth-labelled trough-geometry record.

    Returns a :class:`SyntheticRecord` whose ``truth`` is a
    :class:`TroughGeometryTruthLabels`, mirroring how
    ``generate_timing_identifiability_record`` carries ``TimingTruthLabels``.
    """
    if partition not in {"calibration", "validation"}:
        raise ValueError("partition must be 'calibration' or 'validation'.")
    valid_seeds = (
        GEOMETRY_CALIBRATION_SEEDS if partition == "calibration" else GEOMETRY_VALIDATION_SEEDS
    )
    if seed not in valid_seeds:
        raise ValueError(f"seed {seed} is outside the {partition} partition.")

    rng = np.random.default_rng(np.random.SeedSequence([int(seed), 0x47454F4D]))
    family = _TROUGH_GEOMETRY_FAMILIES[seed % len(_TROUGH_GEOMETRY_FAMILIES)]
    anchor = _GEOMETRY_ANCHOR_MONTH
    n_years = _GEOMETRY_N_YEARS
    index = _monthly_index(n_years)
    months = index.month.to_numpy()

    values = np.full(len(index), _GEOMETRY_BASE_PP, dtype=float)
    valid = np.full(len(index), 100, dtype=int)
    masked = np.zeros(len(index), dtype=bool)

    shifts = [0] * n_years
    identifiable = [True] * n_years
    if family == "stationary_trough":
        pass
    elif family == "wide_phase_excursion":
        pattern = (0, 2, 4, 5, 3, 0, -2, -4, -5, -3, -1, 1)
        shifts = list(pattern[:n_years])
    elif family == "abrupt_phase_shift":
        shifts = [0] * (n_years // 2) + [4] * (n_years - n_years // 2)
    elif family == "competing_secondary_minimum":
        shifts = [int(rng.integers(-2, 3)) for _ in range(n_years)]
    elif family == "tied_low_plateau_wide":
        identifiable = [False] * n_years
    elif family == "missing_outer_months":
        # Half the years put the truth trough at +/-4, inside the masked span.
        # Those years are unidentifiable at every radius, so abstention is the
        # correct answer and widening the window buys nothing.
        shifts = [0, 3, -3, 4, -4, 0, 3, -3, 4, -4, 0, 3][:n_years]
    elif family == "quality_loss_outer_months":
        shifts = [0, 3, -3, 4, -4, 0, 3, -3, 4, -4, 0, 3][:n_years]
    elif family == "zero_dominated_wide_excursion":
        shifts = [0, 4, -4, 5, -5, 2, -2, 3, -3, 1, -1, 0][:n_years]
    elif family == "short_cycle_stress":
        shifts = [(-3 * offset) % 12 - 6 for offset in range(n_years)]
        shifts = [max(-5, min(5, shift)) for shift in shifts]
    elif family == "long_cycle_stress":
        shifts = [(3 * offset) % 12 - 6 for offset in range(n_years)]
        shifts = [max(-5, min(5, shift)) for shift in shifts]

    trough_dates: list[pd.Timestamp | None] = []
    for offset in range(n_years):
        rows = np.arange(offset * 12, (offset + 1) * 12)
        row_months = months[rows]
        trough_month = _geometry_shifted_month(anchor, shifts[offset])
        peak_month = _geometry_shifted_month(trough_month, 6)

        if family == "tied_low_plateau_wide":
            plateau = [_geometry_shifted_month(anchor, step) for step in (-2, -1, 0, 1, 2)]
            values[rows[np.isin(row_months, plateau)]] = _GEOMETRY_TROUGH_PP
            values[rows[row_months == peak_month]] = _GEOMETRY_PEAK_PP
            trough_dates.append(None)
            continue

        values[rows[row_months == trough_month]] = _GEOMETRY_TROUGH_PP
        values[rows[row_months == peak_month]] = _GEOMETRY_PEAK_PP

        if family == "competing_secondary_minimum":
            # Five months out, not six: at six it would land on the peak month
            # and overwrite it, destroying the annual cycle this family needs.
            #
            # The offset above the true trough must survive integer-pixel
            # quantization in ``_geometry_frame``, which rounds every value to
            # whole ``n_water`` counts via
            # ``np.rint(values * n_valid / 100.0)`` at ``n_valid == 100``.  A
            # +0.5 offset (2.0 -> 2.5) rounds right back to the same
            # ``n_water`` as the true trough, so the rival silently ties
            # instead of losing, turning this family into an unlabelled
            # duplicate of ``tied_low_plateau_wide`` while still claiming a
            # single identifiable point truth.  +2.0 (2.0 -> 4.0) rounds to a
            # distinct, strictly higher ``n_water`` (4 vs 2) and stays well
            # clear of ``_GEOMETRY_PEAK_PP`` (70.0).
            rival = _geometry_shifted_month(trough_month, 5)
            values[rows[row_months == rival]] = _GEOMETRY_TROUGH_PP + 2.0
        elif family == "zero_dominated_wide_excursion":
            # Exactly one zero month.  A whole year tied at zero has no point
            # trough at all, so labelling one would invert the false
            # precise-boundary metric: abstention would score as an error.
            values[rows] = 1.0
            values[rows[row_months == peak_month]] = _GEOMETRY_PEAK_PP
            values[rows[row_months == trough_month]] = 0.0
        elif family == "missing_outer_months":
            outer = [
                _geometry_shifted_month(anchor, step)
                for step in (-5, -4, 4, 5)
            ]
            masked[rows[np.isin(row_months, outer)]] = True
        elif family == "quality_loss_outer_months":
            outer = [
                _geometry_shifted_month(anchor, step)
                for step in (-5, -4, 4, 5)
            ]
            valid[rows[np.isin(row_months, outer)]] = 5

        trough_dates.append(_geometry_month(offset, trough_month))

    if family == "missing_outer_months":
        # A truth trough hidden behind a mask is not identifiable at any radius.
        for offset in range(n_years):
            date = trough_dates[offset]
            if date is not None and bool(masked[index.get_loc(date)]):
                identifiable[offset] = False
                trough_dates[offset] = None

    frame = _geometry_frame(index, values, valid=valid, masked=masked)
    observed_shifts = [
        abs(shift) for shift, keep in zip(shifts, identifiable) if keep
    ]
    truth = TroughGeometryTruthLabels(
        climatological_trough_month=anchor,
        n_years=n_years,
        trough_date_by_year=tuple(trough_dates),
        identifiable_by_year=tuple(bool(item) for item in identifiable),
        max_abs_excursion_months=int(max(observed_shifts)) if observed_shifts else 0,
    )
    scenario = ScenarioMetadata("none", "none", 0.0, 0, 0.0)
    return SyntheticRecord(frame=frame, truth=truth, scenario=scenario, family=family, seed=seed)


# ---------------------------------------------------------------------------
# Retrospective peak-to-peak trough-refinement corpus
#
# This corpus has its own seed namespace and truth type. It must not be folded
# into the established evidence, timing, or search-geometry generators because
# doing so would silently alter their frozen family allocation and fingerprints.
# ---------------------------------------------------------------------------

TROUGH_REFINEMENT_CALIBRATION_SEEDS = range(70000, 75000)
TROUGH_REFINEMENT_VALIDATION_SEEDS = range(80000, 85000)

_TROUGH_REFINEMENT_FAMILIES = (
    "ordinary_seasonal",
    "gradual_recovery",
    "long_flat_low_state",
    "low_variability",
    "false_early_rise",
    "one_pulse",
    "two_pulses",
    "disjoint_modes",
    "gap_after_low_state",
    "gap_overlapping_low_state",
    "low_quality_interior",
    "low_quality_peaks",
    "interval_peaks",
    "missing_peaks",
    "short_cycle",
    "long_cycle",
    "open_span",
)


@dataclass(frozen=True)
class TroughRefinementTruth:
    """Detector-visible truth for one generated peak-to-peak span."""

    boundary_start: pd.Timestamp | None
    boundary_end: pd.Timestamp | None
    low_state_start: pd.Timestamp | None
    low_state_end: pd.Timestamp | None
    pulse_months: tuple[pd.Timestamp, ...]
    expected_status: str

    @property
    def resolvable(self) -> bool:
        return self.boundary_start is not None and self.boundary_end is not None


@dataclass(frozen=True)
class TroughRefinementSyntheticRecord:
    frame: pd.DataFrame
    truth: TroughRefinementTruth
    family: str
    seed: int
    left_peak: object
    right_peak: object | None
    # Not real pass-1 output: a synthetic comparator derived from truth
    # (truth interval start, sometimes shifted one month earlier). See
    # `_trough_refinement_calibration._cache_row`'s use of this field.
    synthetic_reference_boundary: pd.Timestamp | None


def _trough_refinement_values(length: int, low_position: int) -> np.ndarray:
    recession = np.linspace(90.0, 8.0, low_position + 1)
    recovery = np.linspace(20.0, 88.0, length - low_position - 1)
    return np.concatenate((recession, recovery))


def generate_trough_refinement_record(
    seed: int,
    *,
    partition: Literal["calibration", "validation"],
) -> TroughRefinementSyntheticRecord:
    """Build one independent, truth-labelled peak-to-peak trough span."""
    from ._state_input import prepare_monthly_extent
    from ._trough_refinement import PeakBoundary

    if partition not in {"calibration", "validation"}:
        raise ValueError("partition must be 'calibration' or 'validation'.")
    valid_seeds = (
        TROUGH_REFINEMENT_CALIBRATION_SEEDS
        if partition == "calibration"
        else TROUGH_REFINEMENT_VALIDATION_SEEDS
    )
    if seed not in valid_seeds:
        raise ValueError(f"seed {seed} is outside the {partition} partition.")

    family = _TROUGH_REFINEMENT_FAMILIES[seed % len(_TROUGH_REFINEMENT_FAMILIES)]
    rng = np.random.default_rng(np.random.SeedSequence([int(seed), 0x54524F55]))
    length = 7 if family == "short_cycle" else 20 if family == "long_cycle" else 13
    low_position = length // 2
    index = pd.date_range("2000-01-01", periods=length, freq="MS")
    values = _trough_refinement_values(length, low_position)
    invalid = np.zeros(length, dtype=float)
    missing: list[int] = []
    low_start = low_end = low_position
    pulse_positions: tuple[int, ...] = ()
    truth_resolvable = True
    expected_status = "confirmed"

    if family == "gradual_recovery":
        values[low_position:] = np.linspace(8.0, 88.0, length - low_position)
        values[low_position + 1] = 8.4
        values[low_position + 2] = 10.0
    elif family == "long_flat_low_state":
        low_start, low_end = low_position - 1, low_position + 1
        values[low_start:low_end + 1] = 8.0
    elif family == "low_variability":
        values = 10.0 + rng.normal(0.0, 0.02, length)
        truth_resolvable = False
        expected_status = "unavailable"
    elif family == "false_early_rise":
        values[low_position - 2:low_position + 2] = [8.0, 18.0, 7.5, 20.0]
        low_position += 0
        pulse_positions = (low_position - 1,)
    elif family == "one_pulse":
        values[low_position - 2:low_position + 2] = [8.0, 42.0, 7.5, 20.0]
        pulse_positions = (low_position - 1,)
    elif family == "two_pulses":
        values[low_position - 4:low_position + 2] = [8.5, 45.0, 8.0, 38.0, 7.5, 20.0]
        pulse_positions = (low_position - 3, low_position - 1)
    elif family == "disjoint_modes":
        values[low_position - 2:low_position + 2] = [7.5, 25.0, 7.5, 20.0]
    elif family == "gap_after_low_state":
        low_start, low_end = low_position - 2, low_position
        values[low_start:low_end + 1] = [8.0, 8.1, 8.2]
        missing = [low_position + 1]
        expected_status = "provisional"
    elif family == "gap_overlapping_low_state":
        values[low_position - 1:low_position + 2] = [8.0, 8.0, 8.0]
        missing = [low_position]
        truth_resolvable = False
        expected_status = "unresolved"
    elif family == "low_quality_interior":
        invalid[low_position - 3] = 55.0
    elif family == "low_quality_peaks":
        invalid[[0, length - 1]] = 55.0
        expected_status = "provisional"
    elif family == "interval_peaks":
        values[1] = values[0] - 0.1
        values[-2] = values[-1] - 0.1
        expected_status = "provisional"
    elif family == "missing_peaks":
        truth_resolvable = False
        expected_status = "unavailable"
    elif family == "open_span":
        truth_resolvable = False
        expected_status = "awaiting_next_peak"

    # Small detector-visible variability is independent of policy and never
    # changes the generator's declared low-state location.
    if family not in {
        "long_flat_low_state",
        "low_variability",
        "gap_after_low_state",
        "gap_overlapping_low_state",
    }:
        noise = rng.normal(0.0, 0.03, length)
        noise[[0, length - 1, low_position]] = 0.0
        if family == "disjoint_modes":
            noise[low_position - 2] = 0.0
        values = np.clip(values + noise, 0.0, 100.0)

    n_aoi = np.full(length, 10000, dtype=int)
    n_valid = np.rint(n_aoi * (1.0 - invalid / 100.0)).astype(int)
    for position in missing:
        n_valid[position] = 0
    n_invalid = n_aoi - n_valid
    n_water = np.rint(np.clip(values, 0.0, 100.0) * n_valid / 100.0).astype(int)
    raw = pd.DataFrame(
        {
            "n_water": n_water,
            "n_valid": n_valid,
            "n_invalid": n_invalid,
            "n_aoi": n_aoi,
        },
        index=index,
    )
    frame = prepare_monthly_extent(raw, quality_policy="flag")

    left_date = pd.Timestamp(index[0])
    right_date = pd.Timestamp(index[-1])
    if family == "missing_peaks":
        left_peak = PeakBoundary.missing()
    elif family == "low_variability":
        left_peak = PeakBoundary(left_date, (left_date,), "unresolved", "normal")
    elif family == "interval_peaks":
        left_peak = PeakBoundary(
            left_date,
            (left_date, pd.Timestamp(index[1])),
            "interval",
            "normal",
        )
    else:
        quality = "low" if family == "low_quality_peaks" else "normal"
        left_peak = PeakBoundary(left_date, (left_date,), "point", quality)

    if family == "open_span":
        right_peak = None
    elif family == "interval_peaks":
        right_peak = PeakBoundary(
            right_date,
            (pd.Timestamp(index[-2]), right_date),
            "interval",
            "normal",
        )
    else:
        quality = "low" if family == "low_quality_peaks" else "normal"
        right_peak = PeakBoundary(right_date, (right_date,), "point", quality)

    if truth_resolvable:
        boundary_start = pd.Timestamp(index[low_start])
        boundary_end = pd.Timestamp(index[low_end])
        low_state_start = boundary_start
        low_state_end = boundary_end
        reference_position = max(1, low_start - (1 if seed % 3 == 0 else 0))
        synthetic_reference_boundary = pd.Timestamp(index[reference_position])
    else:
        boundary_start = boundary_end = None
        low_state_start = low_state_end = None
        synthetic_reference_boundary = pd.Timestamp(index[low_position])

    truth = TroughRefinementTruth(
        boundary_start=boundary_start,
        boundary_end=boundary_end,
        low_state_start=low_state_start,
        low_state_end=low_state_end,
        pulse_months=tuple(pd.Timestamp(index[position]) for position in pulse_positions),
        expected_status=expected_status,
    )
    return TroughRefinementSyntheticRecord(
        frame=frame,
        truth=truth,
        family=family,
        seed=seed,
        left_peak=left_peak,
        right_peak=right_peak,
        synthetic_reference_boundary=synthetic_reference_boundary,
    )
