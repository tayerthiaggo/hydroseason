from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from hydroseason._preflight_types import CandidateMetrics, Decision, PreflightThresholds


@dataclass(frozen=True)
class CandidateEvaluation:
    candidate_metrics: CandidateMetrics
    decision: Decision
    reasons: tuple[str, ...]
    warnings: tuple[str, ...] = ()

    @property
    def raw_metrics(self) -> dict[str, Any]:
        return self.candidate_metrics.to_dict()["raw_metrics"]

    @property
    def metrics(self) -> SimpleNamespace:
        return SimpleNamespace(**self.candidate_metrics.to_dict()["metrics"])

    @property
    def margins(self) -> dict[str, Any]:
        return self.candidate_metrics.to_dict()["margins"]


def _provenance_payload(annual) -> dict[str, Any]:
    provenance = annual.attrs.get("provenance", {})
    if not isinstance(provenance, dict):
        return {}
    return provenance


def _complete_years(annual) -> tuple[int, ...]:
    provenance_years = _provenance_payload(annual).get("complete_years")
    if provenance_years is not None:
        return tuple(int(year) for year in provenance_years)
    return tuple(int(year) for year in annual["year"].values.tolist())


def _complete_annual_subset(annual):
    complete_years = _complete_years(annual)
    available_years = {int(year) for year in annual["year"].values.tolist()}
    selected_years = [year for year in complete_years if year in available_years]
    if not selected_years:
        return annual.isel(year=slice(0, 0))
    return annual.sel(year=selected_years)


def _pixel_area(annual) -> float | None:
    provenance = _provenance_payload(annual)
    raw = provenance.get("pixel_area")
    if raw is None:
        return None
    return float(raw)


def _cache_identity(annual) -> dict[str, Any] | None:
    provenance = _provenance_payload(annual)
    raw = provenance.get("cache_identity_inputs")
    return raw if isinstance(raw, dict) else None


def _eager_item(value) -> Any:
    """``value``'s scalar, computing first if it is Dask-backed.

    Dask does not implement ``.item()`` directly; xarray reductions over a
    lazy (Dask-backed) annual dataset stay lazy, so the scalar must be
    computed explicitly before ``.item()`` is safe to call.
    """
    data = getattr(value, "data", value)
    if hasattr(data, "compute"):
        return value.compute().item()
    return value.item()


def _repeat_distribution(counts) -> dict[str, int]:
    import numpy as np

    flat = np.asarray(counts).astype(int).ravel()
    max_count = int(flat.max()) if flat.size else 0
    return {
        str(repeat_years): int((flat == repeat_years).sum())
        for repeat_years in range(max_count + 1)
    }


def compute_candidate_raw_metrics(annual) -> CandidateMetrics:
    complete_annual = _complete_annual_subset(annual)
    clear = complete_annual["count_clear"]
    wet = complete_annual["count_wet"]
    clear_positive = clear > 0
    clear_repeat = clear_positive.sum("year")
    years = tuple(int(year) for year in complete_annual["year"].values.tolist())

    raw_metrics = {
        "complete_years": list(years),
        "complete_year_count": len(years),
        "pixel_area": _pixel_area(annual),
        "cache_identity": _cache_identity(annual),
        "per_year_clear_pixels": {
            str(int(year)): int(_eager_item(clear_positive.sel(year=year).sum()))
            for year in complete_annual["year"].values
        },
        "clear_year_repeat_distribution": _repeat_distribution(clear_repeat.values),
        "wet_year_repeat_distribution": _repeat_distribution((wet > 0).sum("year").values),
    }
    return CandidateMetrics(raw_metrics=raw_metrics, evidence=annual)


compute_candidate_metrics = compute_candidate_raw_metrics


def _margin_payload(observed: int | float, minimum: int | float) -> dict[str, Any]:
    signed_margin = observed - minimum
    if minimum == 0:
        normalized_margin = None
    else:
        normalized_margin = signed_margin / minimum
    return {
        "observed": observed,
        "minimum": minimum,
        "signed_margin": signed_margin,
        "normalized_margin": normalized_margin,
    }


def _repeat_count(mask) -> int:
    return int(_eager_item(mask.sum()))


def _max_repeat_years(repeat_count) -> int:
    return int(_eager_item(repeat_count.max())) if repeat_count.size else 0


# Mueller et al. 2016 (Remote Sensing of Environment 174:341-352), the
# canonical WOfS validation study DEA's own product docs still cite for
# accuracy: national-mean commission error (non-water misclassified as
# water) is ~8%, concentrated in steep terrain and dense urban areas. This
# is a national average, not a per-pixel truth -- see the docstring on
# _noise_plausible_fraction for what that means for this diagnostic.
DEA_WOFS_COMMISSION_ERROR_RATE = 0.08
_NOISE_SIGNIFICANCE_Z_CRITICAL = 1.645  # one-sided 95% confidence


def _noise_plausible_fraction(repeated_mask, wet_total, clear_total) -> float | None:
    """Fraction of ``repeated_mask`` pixels statistically indistinguishable
    from DEA WOfS classifier noise alone, at the national commission-error
    rate (Mueller et al. 2016, ~8%).

    Uses a normal approximation to the binomial -- justified here since
    ``clear_total`` (observations accumulated over the full requested year
    range) is typically in the tens to hundreds, well past the np>=5 /
    n(1-p)>=5 rule of thumb. Under the null hypothesis that a pixel's true
    water frequency equals the national commission-error rate, the z-score
    for ``wet_total`` hits out of ``clear_total`` looks is
    ``(wet - clear*p_fp) / sqrt(clear*p_fp*(1-p_fp))``. A pixel with z below
    the critical value cannot be distinguished from pure classifier noise at
    this confidence level -- even though it already satisfies the pathway's
    own repeat-count rule.

    This is a diagnostic only. It never changes ``state``/pass-fail: the
    commission-error rate is a NATIONAL AVERAGE (Mueller et al. explicitly
    flag steep terrain and dense urban areas as running well above it), so
    a pixel failing this test is not proven fake, and a pixel passing it is
    not proven real -- silently gating decisions on a national constant
    would be its own kind of bug. Surface it for a human reviewer instead:
    a HIGH fraction here means the pathway's pass rests on pixel counts
    that are cheap to explain away as classifier noise and deserves a
    second look (e.g. checking terrain/shadow at those specific pixels),
    regardless of what the frozen profile's own threshold concluded.

    Returns ``None`` if no pixels satisfy ``repeated_mask`` (nothing to
    assess).
    """
    import numpy as np

    repeated = np.asarray(repeated_mask)
    if not repeated.any():
        return None
    wet_arr = np.asarray(wet_total)[repeated]
    clear_arr = np.asarray(clear_total)[repeated]
    expected = clear_arr * DEA_WOFS_COMMISSION_ERROR_RATE
    variance = clear_arr * DEA_WOFS_COMMISSION_ERROR_RATE * (1 - DEA_WOFS_COMMISSION_ERROR_RATE)
    std = np.sqrt(variance)
    with np.errstate(divide="ignore", invalid="ignore"):
        z = np.where(std > 0, (wet_arr - expected) / std, np.inf)
    not_significant = z < _NOISE_SIGNIFICANCE_Z_CRITICAL
    return float(not_significant.sum()) / float(repeated.sum())


def _pathway_summary(
    *, detected_repeat, clear_repeat, min_pixels: int, min_years: int, wet_total=None, clear_total=None
) -> dict[str, Any]:
    repeated_mask = detected_repeat >= min_years
    repeated_pixels = _repeat_count(repeated_mask)
    opportunity_pixels = _repeat_count(clear_repeat >= min_years)
    detected_years = _max_repeat_years(detected_repeat)
    opportunity_years = _max_repeat_years(clear_repeat)
    passed = repeated_pixels >= min_pixels and detected_years >= min_years
    evaluable = opportunity_pixels >= min_pixels and opportunity_years >= min_years
    if passed:
        state = "pass"
    elif evaluable:
        state = "fail"
    else:
        state = "indeterminate"
    noise_plausible_fraction = None
    if wet_total is not None and clear_total is not None:
        noise_plausible_fraction = _noise_plausible_fraction(repeated_mask, wet_total, clear_total)
    return {
        "state": state,
        "pixels_ever": _repeat_count(detected_repeat >= 1),
        "pixels_repeated": repeated_pixels,
        "years_observed": detected_years,
        "opportunity_pixels_repeated": opportunity_pixels,
        "opportunity_years_observed": opportunity_years,
        "repeat_distribution": _repeat_distribution(detected_repeat.values),
        "noise_plausible_fraction": noise_plausible_fraction,
    }


def evaluate_candidate(raw_metrics: CandidateMetrics, thresholds: PreflightThresholds) -> CandidateEvaluation:
    annual = raw_metrics.evidence
    if annual is None:
        raise ValueError("candidate raw metrics must retain annual evidence for evaluation")

    complete_annual = _complete_annual_subset(annual)
    clear = complete_annual["count_clear"]
    wet = complete_annual["count_wet"]
    frequency = wet / clear.where(clear > 0)
    clear_ok = clear >= thresholds.min_clear_count
    reliable = clear_ok & (frequency >= thresholds.min_frequency_fraction)
    episodic = clear_ok & (wet >= thresholds.min_episodic_wet_count)

    reliable_repeat = reliable.sum("year")
    episodic_repeat = episodic.sum("year")
    clear_repeat = clear_ok.sum("year")
    complete_year_count = int(complete_annual.sizes.get("year", 0))
    # Summed across every complete year, for the noise-significance
    # diagnostic in _pathway_summary -- deliberately not restricted to only
    # the years a pixel happened to qualify in, for maximum statistical
    # power against the classifier-noise null hypothesis.
    wet_total = wet.sum("year")
    clear_total = clear.sum("year")

    recurrent = _pathway_summary(
        detected_repeat=reliable_repeat,
        clear_repeat=clear_repeat,
        min_pixels=thresholds.min_reliable_pixels,
        min_years=thresholds.min_reliable_years,
        wet_total=wet_total,
        clear_total=clear_total,
    )
    episodic_summary = _pathway_summary(
        detected_repeat=episodic_repeat,
        clear_repeat=clear_repeat,
        min_pixels=thresholds.min_episodic_pixels,
        min_years=thresholds.min_episodic_years,
        wet_total=wet_total,
        clear_total=clear_total,
    )

    metrics = {
        "complete_year_count": complete_year_count,
        "recurrent_pixels_ever": recurrent["pixels_ever"],
        "recurrent_pixels_repeated": recurrent["pixels_repeated"],
        "recurrent_years_observed": recurrent["years_observed"],
        "recurrent_opportunity_pixels_repeated": recurrent["opportunity_pixels_repeated"],
        "recurrent_opportunity_years_observed": recurrent["opportunity_years_observed"],
        "recurrent_repeat_distribution": recurrent["repeat_distribution"],
        "recurrent_noise_plausible_fraction": recurrent["noise_plausible_fraction"],
        "episodic_pixels_ever": episodic_summary["pixels_ever"],
        "episodic_pixels_repeated": episodic_summary["pixels_repeated"],
        "episodic_years_observed": episodic_summary["years_observed"],
        "episodic_opportunity_pixels_repeated": episodic_summary["opportunity_pixels_repeated"],
        "episodic_opportunity_years_observed": episodic_summary["opportunity_years_observed"],
        "episodic_repeat_distribution": episodic_summary["repeat_distribution"],
        "episodic_noise_plausible_fraction": episodic_summary["noise_plausible_fraction"],
    }

    reasons: list[str] = []
    warnings: list[str] = []
    if complete_year_count < thresholds.min_candidate_years:
        decision: Decision = "indeterminate"
        reasons.append("candidate_insufficient_complete_years")
    elif recurrent["state"] == "pass" or episodic_summary["state"] == "pass":
        decision = "pass"
        if recurrent["state"] == "pass":
            reasons.append("candidate_recurrent_pass")
        if episodic_summary["state"] == "pass":
            reasons.append("candidate_episodic_pass")
    elif recurrent["state"] == "fail" and episodic_summary["state"] == "fail":
        decision = "fail"
        reasons.append("candidate_both_pathways_failed")
    else:
        decision = "indeterminate"
        reasons.append("candidate_insufficient_observation_opportunity")
        if recurrent["state"] == "fail":
            reasons.append("candidate_recurrent_fail")
        if episodic_summary["state"] == "fail":
            reasons.append("candidate_episodic_fail")

    margins = {
        "candidate_years": _margin_payload(complete_year_count, thresholds.min_candidate_years),
        "recurrent_pixels": _margin_payload(
            recurrent["pixels_repeated"],
            thresholds.min_reliable_pixels,
        ),
        "recurrent_years": _margin_payload(
            recurrent["years_observed"],
            thresholds.min_reliable_years,
        ),
        "episodic_pixels": _margin_payload(
            episodic_summary["pixels_repeated"],
            thresholds.min_episodic_pixels,
        ),
        "episodic_years": _margin_payload(
            episodic_summary["years_observed"],
            thresholds.min_episodic_years,
        ),
    }

    decisive_margin_keys: list[str] = []
    if complete_year_count < thresholds.min_candidate_years:
        decisive_margin_keys.append("candidate_years")
    elif decision == "pass":
        if recurrent["state"] == "pass":
            decisive_margin_keys.extend(("recurrent_pixels", "recurrent_years"))
        if episodic_summary["state"] == "pass":
            decisive_margin_keys.extend(("episodic_pixels", "episodic_years"))
    elif decision == "fail":
        decisive_margin_keys.extend(
            ("recurrent_pixels", "recurrent_years", "episodic_pixels", "episodic_years")
        )
    if any(
        margins[key]["normalized_margin"] is not None
        and abs(float(margins[key]["normalized_margin"])) <= thresholds.near_threshold_margin_fraction
        for key in decisive_margin_keys
    ):
        warnings.append("near_threshold")

    candidate_metrics = CandidateMetrics(
        raw_metrics=raw_metrics.to_dict()["raw_metrics"],
        metrics=metrics,
        margins=margins,
        evidence=annual,
    )
    return CandidateEvaluation(
        candidate_metrics=candidate_metrics,
        decision=decision,
        reasons=tuple(reasons),
        warnings=tuple(dict.fromkeys(warnings)),
    )


__all__ = [
    "CandidateEvaluation",
    "compute_candidate_metrics",
    "compute_candidate_raw_metrics",
    "evaluate_candidate",
]


