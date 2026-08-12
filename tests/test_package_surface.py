import importlib
from importlib import resources
from pathlib import Path


def test_package_import_exposes_only_migration_safe_surface():
    hydroseason = importlib.import_module("hydroseason")

    assert isinstance(hydroseason.__version__, str)
    assert hydroseason.__all__ == [
        "__version__", "HydroYearConfig", "detect_hydrological_years",
        "label_hydrological_months", "monthly_water_extent", "suggest_hydro_year_config",
        "load_aoi", "load_wofs_from_stac", "load_wofs_monthly_extent", "load_monthly_masks",
        "load_monthly_masks_zarr", "load_extent_csv", "complete_monthly_axis",
        "acquire_wofs_cache", "WOfSCacheHandle", "open_wo_statistics", "open_completed_mask_cache",
        "verify_cache_footprints", "open_completed_dual_extent_counts",
        "build_wet_planning_footprint", "WetPlanningFootprint", "HistoricalWaterMask",
        "HistoricalMaskCoverageWarning",
        "build_historical_water_mask", "load_or_build_historical_water_mask",
        "generate_html_report", "CatchmentReportPaths", "generate_catchment_report",
        "DynamicHydroYearConfig", "HydrologicalStateResult",
        "SeasonalPatternResult", "aggregate_basin_monthly_extent",
        "analyze_hydrological_state", "classify_annual_surface_water_condition",
        "classify_seasonal_pattern", "compute_monthly_surface_water_condition",
        "detect_dynamic_hydrological_years", "suggest_dynamic_hydro_year_config",
        "Regime", "WaterRegimeAssessment", "assess_water_regime",
        "WaterEventResult", "extract_water_events",
        "CatchmentAnalysis", "analyze_catchment",
        "HydroSeasonRunResult", "run_hydroseason",
    ]
    assert callable(hydroseason.detect_hydrological_years)
    assert callable(hydroseason.label_hydrological_months)
    assert callable(hydroseason.load_extent_csv)
    assert callable(hydroseason.load_wofs_monthly_extent)
    assert callable(hydroseason.acquire_wofs_cache)
    # open_completed_mask_cache is acquire_wofs_cache's public reader
    # counterpart (Task W2.1): a caller that acquired a cache must be able to
    # read it back through the top-level package surface, not just via the
    # private hydroseason._io_wofs_zarr module.
    assert callable(hydroseason.open_completed_mask_cache)
    # verify_cache_footprints is the public tamper-detection entry point for
    # a cache's persisted full-AOI/analysis-footprint metadata (Task W2.3):
    # HydroFragments calls hydroseason.verify_cache_footprints(handle)
    # directly, so it must be reachable from the top-level package surface,
    # not just via the private hydroseason._io_wofs_zarr module.
    assert callable(hydroseason.verify_cache_footprints)
    # open_completed_dual_extent_counts is the public reader counterpart for
    # composite_bundle="dual_composite_v1" acquisitions (Task W2.2): the
    # second (max_water) composite's per-month counts must be reachable from
    # the top-level package surface, not just via the private
    # hydroseason._io_wofs_zarr module.
    assert callable(hydroseason.open_completed_dual_extent_counts)
    assert callable(hydroseason.build_wet_planning_footprint)
    assert hydroseason.WetPlanningFootprint.__name__ == "WetPlanningFootprint"
    assert hydroseason.HistoricalWaterMask.__name__ == "HistoricalWaterMask"
    assert issubclass(hydroseason.HistoricalMaskCoverageWarning, UserWarning)
    assert callable(hydroseason.build_historical_water_mask)
    assert callable(hydroseason.load_or_build_historical_water_mask)
    assert callable(hydroseason.assess_water_regime)
    assert callable(hydroseason.extract_water_events)
    assert callable(hydroseason.analyze_catchment)
    assert callable(hydroseason.generate_catchment_report)
    assert callable(hydroseason.run_hydroseason)
    assert hydroseason.HydroSeasonRunResult.__name__ == "HydroSeasonRunResult"
    assert "get_monthly_silo_rainfall" not in vars(hydroseason)
    assert "ValidationSeasonConfig" not in vars(hydroseason)

    stripped_names = {
        "classify_rainfall",
        "run_pipeline",
        "read_rainfall",
        "get_monthly_silo_rainfall",
    }
    assert stripped_names.isdisjoint(vars(hydroseason))


def test_package_metadata_declares_only_the_orchestrator_cli():
    """0.1.1 adds exactly one console script: the thin `hydroseason run`
    wrapper around run_hydroseason (see
    docs/superpowers/specs/2026-08-11-cli-case-study-maps-design.md). The
    removed pre-rewrite rainfall CLI must never come back."""
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib

    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["scripts"] == {
        "hydroseason": "hydroseason.cli:main"
    }


def test_invalid_conda_recipe_is_not_shipped():
    assert not Path("conda/meta.yaml").exists()


def test_robust_extrema_and_semi_markov_internals_stay_unexported():
    # Tasks 3-10 added the robust-extrema default detector, its diagnostic
    # columns, and the opt-in semi-Markov challenger entirely behind
    # underscore-prefixed internal modules (_boundary, _boundary_validation,
    # _semi_markov). None of that should have widened the top-level surface:
    # their public symbols must not appear in __all__ or be importable as
    # `hydroseason.<symbol>`. (The submodules themselves become accessible as
    # `hydroseason._boundary` etc. purely as a side effect of Python import
    # machinery once anything imports from them internally -- that is true of
    # every underscore-prefixed module and is not a re-export, so it is not
    # asserted against here.) detect_dynamic_hydrological_years and
    # DynamicHydroYearConfig (already asserted above) remain the only public
    # entry points for this behavior.
    hydroseason = importlib.import_module("hydroseason")

    internal_names = {
        "RobustBoundaryConfig", "BoundarySelection", "select_window_minimum",
        "select_cycle_peak", "select_boundary_sequence", "robust_scale",
        "SemiMarkovConfig", "fit_semi_markov_boundaries",
        "WindowStatus", "SelectionStatus",
        # Task 6 review: experimental detector entry points stay internal.
        "_detect_dynamic_hydrological_years_experimental",
        "_find_semi_markov_trough_opportunities",
    }
    assert internal_names.isdisjoint(vars(hydroseason))
    assert internal_names.isdisjoint(hydroseason.__all__)


def test_report_assets_resolve_from_source_package():
    root = resources.files("hydroseason").joinpath("_assets")

    assert root.joinpath("plotly-basic-3.6.0.min.js").read_text(encoding="utf-8").startswith(
        "/**"
    )
    assert "MIT License" in root.joinpath("PLOTLY-LICENSE.txt").read_text(encoding="utf-8")
