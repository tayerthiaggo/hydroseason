"""Synthetic stress test for HydroSeason rainfall workflows."""

from __future__ import annotations

import argparse
import logging
import sys
import time
import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd

from hydroseason import PipelineArtifacts, classify_rainfall


warnings.filterwarnings(
    "ignore",
    message="KMeans is known to have a memory leak.*",
)


REGIME_CLIMATOLOGIES: dict[str, list[float]] = {
    "monsoonal": [260, 240, 190, 80, 25, 5, 0, 0, 4, 35, 110, 210],
    "mediterranean": [110, 95, 80, 40, 10, 2, 0, 0, 5, 20, 70, 100],
    "bimodal": [45, 70, 190, 230, 190, 35, 10, 12, 45, 160, 220, 115],
    "arid": [5, 30, 4, 1, 0, 0, 0, 0, 0, 0, 1, 3],
    "diffuse": [80, 70, 60, 50, 40, 30, 25, 30, 40, 50, 60, 75],
    "weak": [55, 60, 58, 52, 48, 45, 43, 45, 48, 50, 53, 56],
}


@dataclass(frozen=True)
class CaseSummary:
    index: int
    regime: str
    rows_in: int
    rows_out: int
    detected_regime: str
    elapsed_seconds: float


def build_monthly_rainfall(
    *,
    rng: np.random.Generator,
    regime: str,
    start_year: int,
    n_years: int,
) -> pd.DataFrame:
    dates = pd.date_range(
        f"{start_year}-01-01",
        periods=12 * n_years,
        freq="MS",
    )
    climatology = np.asarray(REGIME_CLIMATOLOGIES[regime], dtype=float)
    base = np.tile(climatology, n_years)

    multiplicative_noise = rng.lognormal(mean=0.0, sigma=0.25, size=base.size)
    additive_noise = rng.normal(0.0, 6.0, size=base.size)
    rainfall = np.clip(base * multiplicative_noise + additive_noise, 0.0, None)

    low_rain_mask = base <= 5.0
    rainfall[low_rain_mask & (rng.random(base.size) < 0.65)] = 0.0

    outlier_count = int(rng.integers(0, 4))
    if outlier_count:
        outlier_indices = rng.choice(
            base.size,
            size=outlier_count,
            replace=False,
        )
        rainfall[outlier_indices] += rng.uniform(
            120.0,
            450.0,
            size=outlier_count,
        )

    monthly = pd.DataFrame(
        {
            "Date": dates,
            "Year": dates.year,
            "Month": dates.month,
            "Rainfall_mm": rainfall,
        }
    )
    return perturb_monthly_input(monthly, rng=rng)


def perturb_monthly_input(
    monthly: pd.DataFrame,
    *,
    rng: np.random.Generator,
) -> pd.DataFrame:
    perturbed = monthly.copy()

    gap_indices: set[int] = set()
    gap_count = int(rng.integers(0, 3))
    for _gap_number in range(gap_count):
        if len(perturbed) <= 8:
            break
        gap_start = int(rng.integers(3, len(perturbed) - 3))
        gap_length = int(rng.integers(1, 3))
        gap_end = min(gap_start + gap_length, len(perturbed) - 2)
        gap_indices.update(range(gap_start, gap_end))
    if gap_indices:
        perturbed = perturbed.drop(index=sorted(gap_indices))

    duplicate_count = int(rng.integers(0, 4))
    if duplicate_count and not perturbed.empty:
        duplicate_rows = perturbed.sample(
            n=min(duplicate_count, len(perturbed)),
            random_state=int(rng.integers(0, 2**32 - 1)),
        ).copy()
        perturbed = pd.concat([perturbed, duplicate_rows], ignore_index=True)

    return perturbed.sample(
        frac=1.0,
        random_state=int(rng.integers(0, 2**32 - 1)),
    ).reset_index(drop=True)


def assert_pipeline_invariants(artifacts: PipelineArtifacts) -> None:
    result = artifacts.result
    required_columns = {
        "Date",
        "Year",
        "Month",
        "Rainfall_mm",
        "SeasonType",
        "Hydro_Year",
    }
    missing_columns = required_columns.difference(result.columns)
    if missing_columns:
        raise AssertionError(
            f"Missing result columns: {sorted(missing_columns)}"
        )

    if result.empty:
        raise AssertionError("Pipeline returned an empty result")
    if result[list(required_columns)].isna().any().any():
        raise AssertionError("Required result columns contain missing values")

    dates = pd.to_datetime(result["Date"])
    if not dates.is_monotonic_increasing:
        raise AssertionError("Result dates are not sorted")
    if not result["Month"].astype(int).equals(dates.dt.month.astype(int)):
        raise AssertionError("Month column does not match Date")

    allowed_seasons = {"Wet", "Dry", "Unclassified"}
    observed_seasons = set(result["SeasonType"].astype(str).unique())
    unexpected_seasons = observed_seasons.difference(allowed_seasons)
    if unexpected_seasons:
        raise AssertionError(
            f"Unexpected SeasonType values: {sorted(unexpected_seasons)}"
        )

    allowed_regimes = {"seasonal", "borderline", "non_seasonal"}
    if artifacts.diagnostics.regime not in allowed_regimes:
        raise AssertionError(
            f"Unexpected diagnostics regime: {artifacts.diagnostics.regime}"
        )
    if not np.isfinite(artifacts.diagnostics.stl_strength):
        raise AssertionError("STL strength is not finite")


def run_stress(
    *,
    cases: int,
    seed: int,
    max_case_seconds: float | None,
    strict_validation: bool,
    verbose: bool,
) -> list[CaseSummary]:
    rng = np.random.default_rng(seed)
    regime_names = sorted(REGIME_CLIMATOLOGIES)
    summaries: list[CaseSummary] = []
    failures: list[str] = []

    for case_index in range(1, cases + 1):
        regime = str(rng.choice(regime_names))
        start_year = int(rng.integers(1950, 2015))
        n_years = int(rng.integers(5, 41))
        monthly = build_monthly_rainfall(
            rng=rng,
            regime=regime,
            start_year=start_year,
            n_years=n_years,
        )

        started = time.perf_counter()
        try:
            artifacts = classify_rainfall(
                monthly,
                raise_on_validation_error=strict_validation,
            )
            assert_pipeline_invariants(artifacts)
        except Exception as exc:  # noqa: BLE001
            failures.append(
                f"case={case_index} regime={regime} start={start_year} "
                f"years={n_years}: {exc}"
            )
            continue

        elapsed_seconds = time.perf_counter() - started
        if max_case_seconds is not None and elapsed_seconds > max_case_seconds:
            failures.append(
                f"case={case_index} regime={regime} exceeded "
                f"{max_case_seconds:.2f}s "
                f"({elapsed_seconds:.2f}s)"
            )

        summary = CaseSummary(
            index=case_index,
            regime=regime,
            rows_in=len(monthly),
            rows_out=len(artifacts.result),
            detected_regime=artifacts.diagnostics.regime,
            elapsed_seconds=elapsed_seconds,
        )
        summaries.append(summary)
        if verbose:
            print(
                f"case={summary.index:03d} source={summary.regime:<14} "
                f"detected={summary.detected_regime:<12} "
                f"rows={summary.rows_in}->{summary.rows_out} "
                f"seconds={summary.elapsed_seconds:.3f}"
            )

    if failures:
        print("STRESS_FAILED", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        raise SystemExit(1)

    return summaries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=int, default=50)
    parser.add_argument("--seed", type=int, default=20260529)
    parser.add_argument("--max-case-seconds", type=float, default=None)
    parser.add_argument(
        "--strict-validation",
        action="store_true",
        help=(
            "Fail on validation errors instead of continuing with "
            "diagnostics."
        ),
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.ERROR,
        format="%(message)s",
    )

    summaries = run_stress(
        cases=args.cases,
        seed=args.seed,
        max_case_seconds=args.max_case_seconds,
        strict_validation=args.strict_validation,
        verbose=args.verbose,
    )
    elapsed = np.array(
        [summary.elapsed_seconds for summary in summaries],
        dtype=float,
    )
    detected = (
        pd.Series([summary.detected_regime for summary in summaries])
        .value_counts()
        .sort_index()
    )
    print(
        "STRESS_OK "
        f"cases={len(summaries)} seed={args.seed} "
        f"p50={np.percentile(elapsed, 50):.3f}s "
        f"p95={np.percentile(elapsed, 95):.3f}s "
        f"max={elapsed.max():.3f}s"
    )
    print(
        "detected_regimes="
        + ", ".join(f"{name}:{count}" for name, count in detected.items())
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
