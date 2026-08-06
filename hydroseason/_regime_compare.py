"""Compare a water-extent regime against the rainfall regime driving it.

``assess_water_regime`` on its own cannot separate two very different stories
that produce the same symptom: a catchment whose surface-water extent shows
no reproducible annual cycle might genuinely sit in an aseasonal climate, or
it might sit in a strongly seasonal climate whose signal is being damped by
regulation, extraction, or storage before it ever reaches the extent record.
Both look identical from extent alone.

Running the same regime assessment on catchment-mean rainfall and comparing
the two verdicts distinguishes them. This module never changes what the
extent regime *is* -- rainfall is read-only context, not an input to
detection -- it only adds an interpretation of why the two might disagree.
"""
from __future__ import annotations

from dataclasses import dataclass

from ._rainfall import monthly_rainfall_to_frame
from ._regime import Regime, WaterRegimeAssessment, assess_water_regime

Divergence = str


@dataclass(frozen=True)
class RegimeComparison:
    """Extent regime, rainfall regime (if supplied), and how they relate."""

    extent: WaterRegimeAssessment
    rainfall: WaterRegimeAssessment | None
    divergence: Divergence
    interpretation: str
    peak_lag_months: int | None

    @property
    def extent_regime(self) -> Regime:
        return self.extent.regime

    @property
    def rainfall_regime(self) -> Regime | None:
        return self.rainfall.regime if self.rainfall is not None else None


def _circular_lag_months(from_month: int, to_month: int) -> int:
    """Shortest signed number of months from ``from_month`` to ``to_month``.

    A plain subtraction reports a December-to-January lag as 11 months; the
    circular form reports 1, which is what "lag" means for a calendar.
    """
    raw = (to_month - from_month) % 12
    return raw if raw <= 6 else raw - 12


_DETERMINATE_REGIMES = {"seasonal", "marginal"}


def compare_extent_and_rainfall_regimes(
    extent,
    rainfall,
    *,
    value_col: str = "extent_pct",
    rainfall_value_col: str = "rainfall_mm",
    date_col: str | None = None,
    min_months_per_year: int = 9,
) -> RegimeComparison:
    """Assess extent and rainfall regimes and interpret their relationship.

    ``rainfall`` may be ``None`` (no ancillary data available), a Series, or a
    DataFrame with a ``rainfall_value_col`` column -- raw SILO output or any
    other monthly rainfall series in the same shape.

    The extent regime returned here is byte-identical to calling
    ``assess_water_regime(extent)`` directly: this function only adds
    rainfall as a second, independently-computed opinion, never feeds it into
    the first.
    """
    extent_regime = assess_water_regime(
        extent, value_col=value_col, date_col=date_col, min_months_per_year=min_months_per_year
    )
    return compare_rainfall_to_extent_regime(
        extent_regime,
        rainfall,
        rainfall_value_col=rainfall_value_col,
        date_col=date_col,
        min_months_per_year=min_months_per_year,
    )


def compare_rainfall_to_extent_regime(
    extent_regime: WaterRegimeAssessment,
    rainfall,
    *,
    rainfall_value_col: str = "rainfall_mm",
    date_col: str | None = None,
    min_months_per_year: int = 9,
) -> RegimeComparison:
    """Interpret an already-computed extent regime against ancillary rainfall.

    This is the authoritative comparison entry point: it takes the extent
    regime as an already-built ``WaterRegimeAssessment`` rather than raw
    extent data, so there is no path -- accidental or otherwise -- for
    rainfall to feed back into extent/regime computation. Callers that only
    have raw extent should use ``compare_extent_and_rainfall_regimes``, which
    computes the assessment and delegates here.

    ``rainfall`` may be ``None`` (no ancillary data available), a Series, or a
    DataFrame with a ``rainfall_value_col`` column -- raw SILO output or any
    other monthly rainfall series in the same shape.
    """
    if rainfall is None:
        return RegimeComparison(
            extent=extent_regime,
            rainfall=None,
            divergence="no_rainfall",
            interpretation=(
                "No rainfall series supplied; extent regime reported on its own. "
                "Add SILO rainfall for this catchment to compare the local rainfall "
                "cycle with observed surface-water extent."
            ),
            peak_lag_months=None,
        )
    rainfall_frame = monthly_rainfall_to_frame(
        rainfall,
        value_col=rainfall_value_col,
        date_col=date_col,
    )
    rainfall_regime = assess_water_regime(
        rainfall_frame,
        min_months_per_year=min_months_per_year,
    )
    peak_lag = None
    if (
        extent_regime.climatological_peak_month is not None
        and rainfall_regime.climatological_peak_month is not None
    ):
        peak_lag = _circular_lag_months(
            rainfall_regime.climatological_peak_month,
            extent_regime.climatological_peak_month,
        )
    divergence, interpretation = _interpret(
        extent_regime, rainfall_regime, peak_lag
    )
    return RegimeComparison(
        extent=extent_regime,
        rainfall=rainfall_regime,
        divergence=divergence,
        interpretation=interpretation,
        peak_lag_months=peak_lag,
    )


def _interpret(
    extent: WaterRegimeAssessment, rainfall: WaterRegimeAssessment, peak_lag: int | None
) -> tuple[Divergence, str]:
    e, r = extent.regime, rainfall.regime

    if r == "insufficient_record":
        return "rainfall_insufficient", (
            "Rainfall record too short to assess (fewer than 5 usable years); "
            "extent regime stands on its own."
        )
    if e == "insufficient_record":
        return "extent_insufficient", (
            "Extent record too short to assess; rainfall regime computed for "
            "reference only."
        )

    if e == "seasonal" and r == "seasonal":
        lag_text = f" Peak lags rainfall by {peak_lag} month(s)." if peak_lag is not None else ""
        return "agree", (
            "Both rainfall and observed surface-water extent show a reproducible "
            f"annual cycle.{lag_text} Water availability here plausibly tracks "
            "local rainfall seasonality; this is consistent with, not proof of, a "
            "direct rainfall-driven relationship."
        )

    if r in _DETERMINATE_REGIMES and e in ("aseasonal", "marginal") and e != r:
        return "extent_damped", (
            f"Rainfall is {r} but observed surface-water extent is {e}: the "
            "catchment's rainfall input has a seasonal cycle that its surface-water "
            "record does not show as clearly. This pattern is consistent with river "
            "regulation, storage operation, extraction, or diversion damping the "
            "natural seasonal signal before it reaches the extent record -- it is "
            "evidence about water management at this catchment, not about its "
            "underlying climate. Confirm against known infrastructure before "
            "concluding regulation specifically."
        )

    if e in _DETERMINATE_REGIMES and r in ("aseasonal", "marginal") and e != r:
        return "extent_more_seasonal", (
            f"Observed surface-water extent is {e} but rainfall is {r}: the extent "
            "record shows more seasonal structure than local rainfall alone would "
            "predict. Consider upstream inflow from outside this catchment, snowmelt, "
            "or a rainfall record that does not represent the catchment well."
        )

    if e == "aseasonal" and r == "aseasonal":
        return "agree", (
            "Both rainfall and observed surface-water extent are aseasonal: the "
            "absence of a reproducible annual cycle in the extent record is "
            "consistent with an aseasonal local rainfall climate, not obviously "
            "evidence of a non-rainfall driver."
        )

    return "partial", (
        f"Extent regime is {e}, rainfall regime is {r}. No single interpretation "
        "template applies; compare the two regime assessments directly."
    )


__all__ = [
    "Divergence",
    "RegimeComparison",
    "compare_extent_and_rainfall_regimes",
    "compare_rainfall_to_extent_regime",
]
