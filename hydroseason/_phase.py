"""Monthly hydrological phase helpers anchored to robust annual cycles.

Phase labels are a separate monthly product. They never rewrite annual
boundaries, peaks, troughs, or condition baselines.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from ._dynamic_year import DynamicHydroYearConfig

PHASES = ("recovery", "wet", "recession", "dry")
PHASE_COLUMNS = [
    "hy_year", "phase", "phase_status", "phase_confidence", "phase_method",
    "boundary_basis", "p_wet", "p_recession", "p_dry", "p_recovery",
    "extent_pct", "candidate_usable",
]


def empty_monthly_phase(prepared: pd.DataFrame, *, method: str = "none") -> pd.DataFrame:
    """Return the stable monthly-phase schema with phase labelling disabled."""
    frame = pd.DataFrame(index=pd.DatetimeIndex(prepared.index))
    frame["hy_year"] = pd.Series(pd.NA, index=frame.index, dtype="Int64")
    frame["phase"] = "unspecified"
    frame["phase_status"] = "disabled"
    frame["phase_confidence"] = np.nan
    frame["phase_method"] = method
    frame["boundary_basis"] = "robust_extrema"
    frame["p_wet"] = np.nan
    frame["p_recession"] = np.nan
    frame["p_dry"] = np.nan
    frame["p_recovery"] = np.nan
    frame["extent_pct"] = prepared["extent_pct"].to_numpy(dtype=float)
    frame["candidate_usable"] = prepared["candidate_usable"].to_numpy(dtype=bool)
    return frame.loc[:, PHASE_COLUMNS]


def assign_monthly_phases(
    prepared: pd.DataFrame,
    hydro_years: pd.DataFrame,
    config: DynamicHydroYearConfig,
    *,
    noise_pp: float,
) -> pd.DataFrame:
    """Dispatch monthly phase labelling without mutating annual products."""
    _ = hydro_years, noise_pp
    if config.phase_model == "none":
        return empty_monthly_phase(prepared)
    raise NotImplementedError("phase_model='rule_based' is implemented in Task 4")
