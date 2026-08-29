from __future__ import annotations

import importlib
import inspect
import json
from dataclasses import replace
from unittest.mock import Mock

import pandas as pd
import pytest

from hydroseason._io_dea_stats import WoStatisticsUnavailable
from hydroseason._preflight_feasibility import FeasibilityResult
from hydroseason._preflight_monthly import MonthlyEvaluation
from hydroseason._preflight_types import (
    MonthlyMetrics,
    MonthlyObservationCapabilities,
    MonthlyObservationRecord,
    PreflightResult,
    PreflightThresholds,
)


@pytest.fixture
def annual_stats():
    xr = pytest.importorskip("xarray")

    dataset = xr.Dataset(
        data_vars={
            "count_wet": (("year", "y", "x"), [[[2, 2]], [[2, 2]]]),
            "count_clear": (("year", "y", "x"), [[[4, 4]], [[4, 4]]]),
        },
        coords={"year": [2005, 2006], "y": [0.0], "x": [0.0, 1.0]},
    )
    dataset.attrs["provenance"] = {
        "complete_years": [2005, 2006],
        "pixel_area": 900.0,
        "item_ids_by_year": {"2005": ["item-1"], "2006": ["item-2"]},
    }
    return dataset


@pytest.fixture
def monthly_record() -> MonthlyObservationRecord:
    frame = pd.DataFrame(
        {
            "n_water": [2, 2],
            "n_valid": [3, 3],
            "n_invalid": [1, 1],
            "n_aoi": [4, 4],
        },
        index=pd.to_datetime(["2005-01-01", "2005-02-01"]),
    )
    return MonthlyObservationRecord(
        frame=frame,
        capabilities=MonthlyObservationCapabilities(
            per_month_pixel_counts=True,
            unique_monthly_pixels=False,
            candidate_monthly_overlap=False,
            exact_geometry=False,
            exact_time_window=True,
        ),
        source_identity={"kind": "dataframe", "content_fingerprint": "abc123"},
    )


def test_public_signature_is_stable():
    public = importlib.import_module("hydroseason")

    signature = inspect.signature(public.preflight)

    assert list(signature.parameters) == [
        "aoi",
        "start_date",
        "end_date",
        "monthly_observations",
        "thresholds",
        "stac_url",
        "statistics_product",
        "resolution",
        "feasibility_only",
        "crs",
        "chunks",
        "cache_dir",
        "prune_to_wet_aoi",
        "wet_aoi_min_frequency_fraction",
        "wet_aoi_require_year_union",
        "max_invalid_pct",
        "quality_policy",
        "allow_unknown_quality",
    ]
    assert signature.parameters["monthly_observations"].default is None
    assert signature.parameters["thresholds"].default == "default"


def test_regular_preflight_reuses_one_loaded_statistics_read(monkeypatch):
    xr = pytest.importorskip("xarray")
    module = importlib.import_module("hydroseason.preflight")
    import hydroseason.io as io

    statistics = xr.Dataset(
        {
            "count_wet": (("y", "x"), [[10, 10], [10, 10]]),
            "count_clear": (("y", "x"), [[20, 20], [20, 20]]),
        },
        coords={"y": [0, 1], "x": [0, 1]},
        attrs={"provenance": {"product": "ga_ls_wo_fq_myear_3"}},
    )
    mask = object()
    events = []
    open_calls = []
    captured = {}

    def fake_open(*args, **kwargs):
        open_calls.append((args, kwargs))
        events.append("read")
        return statistics

    def fake_assess(dataset, *, resolution):
        events.append("screen")
        captured["screen"] = dataset
        return FeasibilityResult(True, resolution, 4, 1, 4, 4, "recurrent_water_present")

    def fake_build(dataset, aoi):
        events.append("max_water")
        captured["mask"] = dataset
        return mask

    monkeypatch.setattr(io, "open_wo_statistics", fake_open)
    monkeypatch.setattr(io, "build_historical_water_mask", fake_build)
    monkeypatch.setattr(module, "assess_feasibility", fake_assess)

    result = module.run_regular_preflight(
        "aoi", "2000-01-01", "2020-12-31", stac_url="https://example.test/stac"
    )

    assert events == ["read", "screen", "max_water"]
    assert len(open_calls) == 1
    assert set(captured["screen"].data_vars) == {"count_wet", "count_clear"}
    assert captured["mask"] is captured["screen"]
    assert result.historical_water_mask is mask


def test_candidate_only_never_normalizes_or_acquires_monthly(monkeypatch, annual_stats):
    public = importlib.import_module("hydroseason")
    module = importlib.import_module("hydroseason.preflight")

    monkeypatch.setattr(module, "open_annual_wo_statistics", lambda *a, **k: annual_stats)
    monthly_called = {"value": False}

    def _forbidden(*_args, **_kwargs):
        monthly_called["value"] = True
        raise AssertionError("monthly path called")

    monkeypatch.setattr(module, "normalize_monthly_observations", _forbidden)

    result = public.preflight(
        "aoi.geojson",
        "2005-01-01",
        "2006-12-31",
        thresholds=PreflightThresholds.testing(),
    )

    assert isinstance(result, PreflightResult)
    assert result.candidate_decision == "pass"
    assert result.monthly_decision == "not_assessed"
    assert result.timing_decision == "not_assessed"
    assert "monthly_not_supplied" in result.reasons
    assert monthly_called["value"] is False


def test_candidate_plus_monthly_runs_both_stages(monkeypatch, annual_stats, monthly_record):
    public = importlib.import_module("hydroseason")
    module = importlib.import_module("hydroseason.preflight")

    monkeypatch.setattr(module, "open_annual_wo_statistics", lambda *a, **k: annual_stats)
    monkeypatch.setattr(
        module,
        "normalize_monthly_observations",
        lambda *_args, **_kwargs: monthly_record,
    )

    result = public.preflight(
        "aoi.geojson",
        "2005-01-01",
        "2006-12-31",
        monthly_observations=monthly_record.frame,
        thresholds=PreflightThresholds.testing(),
    )

    assert result.candidate_decision == "pass"
    assert result.monthly_decision == "fail"
    assert result.timing_decision == "fail"
    assert result.to_dict(flat=False)["provenance"]["monthly"]["source"] == monthly_record.source_identity


def test_diagnostic_mode_reports_raw_metrics_without_hidden_threshold(monkeypatch, annual_stats):
    public = importlib.import_module("hydroseason")
    module = importlib.import_module("hydroseason.preflight")

    candidate_evaluate_called = {"value": False}
    monthly_evaluate_called = {"value": False}

    monkeypatch.setattr(module, "open_annual_wo_statistics", lambda *a, **k: annual_stats)

    def _candidate_forbidden(*_args, **_kwargs):
        candidate_evaluate_called["value"] = True
        raise AssertionError("candidate policy should not run")

    def _monthly_forbidden(*_args, **_kwargs):
        monthly_evaluate_called["value"] = True
        raise AssertionError("monthly policy should not run")

    monkeypatch.setattr(module, "evaluate_candidate", _candidate_forbidden)
    monkeypatch.setattr(module, "evaluate_monthly", _monthly_forbidden)

    result = public.preflight(
        "aoi.geojson",
        "2005-01-01",
        "2006-12-31",
        thresholds="diagnostic",
    )

    assert result.candidate_decision == "not_assessed"
    assert result.monthly_decision == "not_assessed"
    assert result.timing_decision == "not_assessed"
    assert result.candidate_metrics.to_dict()["raw_metrics"]["complete_year_count"] == 2
    assert result.reasons == ("diagnostic_mode", "monthly_not_supplied")
    assert result.thresholds.profile_name == "diagnostic"
    assert result.thresholds.profile_status == "provisional"
    assert result.thresholds.profile_hash != PreflightThresholds.testing().profile_hash
    assert candidate_evaluate_called["value"] is False
    assert monthly_evaluate_called["value"] is False


def test_default_threshold_mode_requires_installed_profile():
    module = importlib.import_module("hydroseason.preflight")

    with pytest.raises(module.PreflightProfileUnavailable, match="finish the calibration/freeze checkpoint"):
        module.preflight("aoi.geojson", "2005-01-01", "2006-12-31")


def test_explicit_thresholds_are_forwarded_to_both_policy_stages(
    monkeypatch, annual_stats, monthly_record,
):
    module = importlib.import_module("hydroseason.preflight")
    thresholds = replace(PreflightThresholds.testing(), min_candidate_years=7)
    seen: dict[str, object] = {}

    monkeypatch.setattr(module, "open_annual_wo_statistics", lambda *a, **k: annual_stats)
    monkeypatch.setattr(
        module,
        "normalize_monthly_observations",
        lambda *_args, **_kwargs: monthly_record,
    )

    def _candidate_stub(raw_metrics, forwarded_thresholds):
        seen["candidate"] = forwarded_thresholds
        return type(
            "CandidateEval",
            (),
            {
                "candidate_metrics": raw_metrics,
                "decision": "indeterminate",
                "reasons": ("candidate_stub",),
                "warnings": (),
            },
        )()

    def _monthly_stub(record, _candidate_evaluation, forwarded_thresholds, **_kwargs):
        seen["monthly"] = forwarded_thresholds
        return MonthlyEvaluation(
            monthly_metrics=MonthlyMetrics(metrics={"supported_month_count": 0}),
            run_decision="not_assessed",
            timing_decision="not_assessed",
            run_reasons=("monthly_stub",),
        )

    monkeypatch.setattr(module, "evaluate_candidate", _candidate_stub)
    monkeypatch.setattr(module, "evaluate_monthly", _monthly_stub)

    result = module.preflight(
        "aoi.geojson",
        "2005-01-01",
        "2006-12-31",
        monthly_observations=monthly_record.frame,
        thresholds=thresholds,
    )

    assert seen == {"candidate": thresholds, "monthly": thresholds}
    assert result.candidate_decision == "indeterminate"
    assert result.monthly_decision == "not_assessed"


def test_arbitrary_dates_are_forwarded_verbatim(monkeypatch, annual_stats, monthly_record):
    module = importlib.import_module("hydroseason.preflight")
    calls: list[tuple[str, str]] = []

    def _annual_stub(*_args, **kwargs):
        calls.append((kwargs["start_date"], kwargs["end_date"]))
        return annual_stats

    def _monthly_stub(_observations, *, start_date, end_date, **_kwargs):
        calls.append((start_date, end_date))
        return monthly_record

    monkeypatch.setattr(module, "open_annual_wo_statistics", _annual_stub)
    monkeypatch.setattr(module, "normalize_monthly_observations", _monthly_stub)

    module.preflight(
        "aoi.geojson",
        "2005-01-15T12:34:56",
        "2006-12-20T01:02:03",
        monthly_observations=monthly_record.frame,
        thresholds=PreflightThresholds.testing(),
    )

    assert calls == [
        ("2005-01-15T12:34:56", "2006-12-20T01:02:03"),
        ("2005-01-15T12:34:56", "2006-12-20T01:02:03"),
    ]


def test_service_outage_is_not_scientific_failure(monkeypatch):
    public = importlib.import_module("hydroseason")
    module = importlib.import_module("hydroseason.preflight")

    monkeypatch.setattr(module, "open_annual_wo_statistics", Mock(side_effect=WoStatisticsUnavailable("offline")))

    result = public.preflight(
        "aoi.geojson",
        "2005-01-01",
        "2006-12-31",
        thresholds=PreflightThresholds.testing(),
    )

    assert result.candidate_decision == "indeterminate"
    assert result.candidate_eligible is None
    assert "statistics_unavailable" in result.reasons
    assert any("offline" in warning for warning in result.warnings)


def test_malformed_monthly_provenance_becomes_warning(monkeypatch, annual_stats, monthly_record):
    public = importlib.import_module("hydroseason")
    module = importlib.import_module("hydroseason.preflight")
    malformed = replace(monthly_record, source_identity="bad-provenance")

    monkeypatch.setattr(module, "open_annual_wo_statistics", lambda *a, **k: annual_stats)
    monkeypatch.setattr(
        module,
        "normalize_monthly_observations",
        lambda *_args, **_kwargs: malformed,
    )

    result = public.preflight(
        "aoi.geojson",
        "2005-01-01",
        "2006-12-31",
        monthly_observations=monthly_record.frame,
        thresholds=PreflightThresholds.testing(),
    )

    assert "monthly_provenance_invalid" in result.warnings
    assert result.to_dict(flat=False)["provenance"]["monthly"]["source"] == {}


def test_result_serialization_is_json_safe(monkeypatch, annual_stats):
    public = importlib.import_module("hydroseason")
    module = importlib.import_module("hydroseason.preflight")

    monkeypatch.setattr(module, "open_annual_wo_statistics", lambda *a, **k: annual_stats)

    result = public.preflight(
        "aoi.geojson",
        "2005-01-01",
        "2006-12-31",
        thresholds=PreflightThresholds.testing(),
    )

    nested = result.to_dict(flat=False)
    flat = result.to_dict(flat=True)

    json.dumps(nested, sort_keys=True)
    json.dumps(flat, sort_keys=True)
    assert "DataFrame" not in flat["metrics_json"]


def test_monthly_programming_type_error_propagates(monkeypatch, annual_stats, monthly_record):
    module = importlib.import_module("hydroseason.preflight")

    monkeypatch.setattr(module, "open_annual_wo_statistics", lambda *a, **k: annual_stats)
    monkeypatch.setattr(
        module,
        "normalize_monthly_observations",
        Mock(side_effect=TypeError("programming bug")),
    )

    with pytest.raises(TypeError, match="programming bug"):
        module.preflight(
            "aoi.geojson",
            "2005-01-01",
            "2006-12-31",
            monthly_observations=monthly_record.frame,
            thresholds=PreflightThresholds.testing(),
        )


def test_package_surface_exports_only_the_public_preflight_names():
    public = importlib.import_module("hydroseason")

    assert callable(public.preflight)
    assert public.PreflightResult.__name__ == "PreflightResult"
    assert public.PreflightThresholds.__name__ == "PreflightThresholds"
    assert "preflight_many" not in vars(public)


def test_run_hydroseason_binding_is_unchanged():
    public = importlib.import_module("hydroseason")
    workflow = importlib.import_module("hydroseason.workflow")

    assert public.run_hydroseason is workflow.run_hydroseason


def test_preflight_forwards_prune_to_wet_aoi_flag(monkeypatch):
    module = importlib.import_module("hydroseason.preflight")

    captured = {}

    def fake_open_annual_wo_statistics(*_args, **kwargs):
        captured["prune_to_wet_aoi"] = kwargs.get("prune_to_wet_aoi")
        raise module.AnnualStatisticsUnavailable("stop before monthly stage")

    monkeypatch.setattr(module, "open_annual_wo_statistics", fake_open_annual_wo_statistics)

    module.preflight(
        aoi="unused",
        start_date="2005-01-01",
        end_date="2005-12-31",
        prune_to_wet_aoi=False,
        thresholds=PreflightThresholds.testing(),
    )

    assert captured["prune_to_wet_aoi"] is False


def test_preflight_forwards_wet_aoi_min_frequency_fraction(monkeypatch):
    module = importlib.import_module("hydroseason.preflight")

    captured = {}

    def fake_open_annual_wo_statistics(*_args, **kwargs):
        captured["wet_aoi_min_frequency_fraction"] = kwargs.get("wet_aoi_min_frequency_fraction")
        raise module.AnnualStatisticsUnavailable("stop before monthly stage")

    monkeypatch.setattr(module, "open_annual_wo_statistics", fake_open_annual_wo_statistics)

    module.preflight(
        aoi="unused",
        start_date="2005-01-01",
        end_date="2005-12-31",
        wet_aoi_min_frequency_fraction=0.1,
        thresholds=PreflightThresholds.testing(),
    )

    assert captured["wet_aoi_min_frequency_fraction"] == 0.1


def test_preflight_forwards_wet_aoi_require_year_union(monkeypatch):
    module = importlib.import_module("hydroseason.preflight")

    captured = {}

    def fake_open_annual_wo_statistics(*_args, **kwargs):
        captured["wet_aoi_require_year_union"] = kwargs.get("wet_aoi_require_year_union")
        raise module.AnnualStatisticsUnavailable("stop before monthly stage")

    monkeypatch.setattr(module, "open_annual_wo_statistics", fake_open_annual_wo_statistics)

    module.preflight(
        aoi="unused",
        start_date="2005-01-01",
        end_date="2005-12-31",
        wet_aoi_require_year_union=True,
        thresholds=PreflightThresholds.testing(),
    )

    assert captured["wet_aoi_require_year_union"] is True


def test_preflight_defaults_wet_aoi_require_year_union_to_false(monkeypatch):
    module = importlib.import_module("hydroseason.preflight")

    captured = {}

    def fake_open_annual_wo_statistics(*_args, **kwargs):
        captured["wet_aoi_require_year_union"] = kwargs.get("wet_aoi_require_year_union")
        raise module.AnnualStatisticsUnavailable("stop before monthly stage")

    monkeypatch.setattr(module, "open_annual_wo_statistics", fake_open_annual_wo_statistics)

    module.preflight(
        aoi="unused",
        start_date="2005-01-01",
        end_date="2005-12-31",
        thresholds=PreflightThresholds.testing(),
    )

    assert captured["wet_aoi_require_year_union"] is False

