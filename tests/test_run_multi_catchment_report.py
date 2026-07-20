"""Tests for scripts/run_multi_catchment_report.py's resolution gate/probe wiring.

These exercise the CLI argument plumbing and resolution-selection LOGIC with
mocked ``probe_amplitude``/``plan_resolution``/``load_wofs_monthly_extent``/
``analyze_hydrological_state`` -- no real network or
STAC access, no real raster compute. The module under test lives outside the
``hydroseason`` package (it's a standalone script in ``scripts/``), so it is
loaded directly from its file path via ``importlib``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest

from hydroseason.io import _DEFAULT_CANDIDATE_RES_M

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "run_multi_catchment_report.py"


def _load_module():
    """Import scripts/run_multi_catchment_report.py fresh under a scratch name.

    A fresh module object per call avoids cross-test monkeypatch bleed (each
    test gets its own module-level bindings of ``probe_amplitude`` etc. to
    patch independently).
    """
    spec = importlib.util.spec_from_file_location(
        "run_multi_catchment_report_under_test", SCRIPT_PATH
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def mod():
    m = _load_module()
    yield m
    sys.modules.pop(m.__name__, None)


class _FakePattern:
    """Picklable stand-in for SeasonalPatternResult (only .pattern is read here)."""

    def __init__(self, pattern="unimodal"):
        self.pattern = pattern


class _FakeConfig:
    """Picklable stand-in for DynamicHydroYearConfig (opaque to this module)."""


class _FakeState:
    """Picklable stand-in for HydrologicalStateResult."""

    def __init__(self):
        self.pattern = _FakePattern()
        self.config = _FakeConfig()
        self.hydro_years = pd.DataFrame({"year": [2020, 2021]})
        self.monthly_condition = pd.DataFrame({"month": [1, 2]})
        self.data_quality = {"ok": True}


def _fake_state():
    return _FakeState()


def _fake_extent(n_valid_values):
    return pd.DataFrame(
        {
            "n_valid": n_valid_values,
            "extent_pct": [10.0] * len(n_valid_values),
        }
    )


def _patch_common(mod, monkeypatch, *, plan_resolution_return, guard_return=None, n_valid=(100, 200, 300)):
    """Patch the four collaborators run_one_catchment calls, with sane defaults."""
    guard_return = guard_return or {
        "amplitude_pp": 5.0,
        "water_fraction_by_res": {300: 0.5, 500: 0.5},
        "guard_caveat": None,
        "refuse_coarsen_past": None,
    }
    probe_mock = Mock(return_value=guard_return)
    plan_mock = Mock(return_value=plan_resolution_return)
    load_mock = Mock(return_value=_fake_extent(list(n_valid)))
    extent_mock = load_mock
    state_mock = Mock(return_value=_fake_state())

    monkeypatch.setattr(mod, "probe_amplitude", probe_mock)
    monkeypatch.setattr(mod, "plan_resolution", plan_mock)
    monkeypatch.setattr(mod, "load_wofs_monthly_extent", load_mock)
    monkeypatch.setattr(mod, "analyze_hydrological_state", state_mock)

    return probe_mock, plan_mock, load_mock, extent_mock, state_mock


def _fake_spec(mod, key="test_catchment"):
    return mod.CatchmentSpec(key, "Test Catchment", "Test River", "Test Region", "note")


def _fake_geo():
    return {
        "area_km2": 1234.0,
        "n_stream_reaches": 10,
        "bounds_wgs84": [140.0, -20.0, 140.5, -19.5],
    }


@pytest.fixture(autouse=True)
def _no_geo_summary(monkeypatch):
    # _catchment_geo_summary reads real geoparquet fixtures from disk; none of
    # these tests care about real boundary geometry, so it is patched per-test
    # via the module fixture below instead (kept here only as documentation
    # that this file intentionally never touches data/catchments/).
    yield


class TestResolutionOverride:
    def test_resolution_override_is_used_verbatim_and_gate_still_called(self, mod, monkeypatch, tmp_path):
        monkeypatch.setattr(mod, "CATCHMENTS_DIR", tmp_path)
        monkeypatch.setattr(mod, "OUTPUT_DIR", tmp_path / "out")
        monkeypatch.setattr(mod, "_catchment_geo_summary", lambda key: _fake_geo())

        probe_mock, plan_mock, load_mock, extent_mock, state_mock = _patch_common(
            mod, monkeypatch,
            plan_resolution_return=(100.0, 2.0, 0.01, "ok"),
        )

        spec = _fake_spec(mod)
        result = mod.run_one_catchment(
            spec, force=False, resolution_override=42.0, allow_large=False, memory_budget_gb=12.0,
        )

        # gate + probe are still called for stamping/visibility ...
        assert probe_mock.called
        assert plan_mock.called
        # ... but the override wins for the resolution actually used in the full load.
        assert result["resolution_m"] == 42.0
        _, load_kwargs = load_mock.call_args
        assert load_kwargs["resolution"] == 42.0


class TestGuardClamp:
    def test_refuse_coarsen_past_clamps_coarser_gate_pick(self, mod, monkeypatch, tmp_path):
        monkeypatch.setattr(mod, "CATCHMENTS_DIR", tmp_path)
        monkeypatch.setattr(mod, "OUTPUT_DIR", tmp_path / "out")
        monkeypatch.setattr(mod, "_catchment_geo_summary", lambda key: _fake_geo())

        # Gate's unclamped pick is 300 m, but the guard refuses to coarsen past 100 m.
        # Re-derivation call (candidate ladder trimmed to <=100m) returns 100m with
        # its own (different, correctly re-priced) peak_gb/floor_pp.
        call_results = [
            (300.0, 9.0, 0.001, "coarsened"),  # first call: unclamped gate pick
            (100.0, 3.0, 0.01, "coarsened"),   # second call: re-planned within guard limit
        ]
        plan_mock = Mock(side_effect=call_results)
        guard_return = {
            "amplitude_pp": 5.0,
            "water_fraction_by_res": {300: 0.2, 500: 0.05},
            "guard_caveat": "Thin-channel guard: ...",
            "refuse_coarsen_past": 100.0,
        }
        monkeypatch.setattr(mod, "probe_amplitude", Mock(return_value=guard_return))
        monkeypatch.setattr(mod, "plan_resolution", plan_mock)
        monkeypatch.setattr(mod, "load_wofs_monthly_extent", Mock(return_value=_fake_extent([100, 200])))
        monkeypatch.setattr(mod, "analyze_hydrological_state", Mock(return_value=_fake_state()))

        spec = _fake_spec(mod)
        result = mod.run_one_catchment(
            spec, force=False, resolution_override=None, allow_large=False, memory_budget_gb=12.0,
        )

        assert result["resolution_m"] == 100.0
        assert result["resolution_m"] <= guard_return["refuse_coarsen_past"]
        # the re-derived cost numbers (from the second plan_resolution call) are used,
        # not the stale unclamped-pick numbers from the first call.
        assert result["projected_noise_floor_pp"] == 0.01
        assert plan_mock.call_count == 2


class TestAllowLargeBypass:
    def test_allow_large_bypasses_native_no_fit_memory_veto(self, mod, monkeypatch, tmp_path):
        monkeypatch.setattr(mod, "CATCHMENTS_DIR", tmp_path)
        monkeypatch.setattr(mod, "OUTPUT_DIR", tmp_path / "out")
        monkeypatch.setattr(mod, "_catchment_geo_summary", lambda key: _fake_geo())

        # First call (real budget): even coarsest candidate exceeds budget -> native_no_fit.
        # Second call (bypass w/ effectively infinite budget): picks the finest candidate.
        call_results = [
            (300.0, 50.0, 0.001, "native_no_fit"),
            (30.0, 1e9, 0.00001, "ok"),
        ]
        plan_mock = Mock(side_effect=call_results)
        monkeypatch.setattr(mod, "probe_amplitude", Mock(return_value={
            "amplitude_pp": 5.0, "water_fraction_by_res": {}, "guard_caveat": None,
            "refuse_coarsen_past": None,
        }))
        monkeypatch.setattr(mod, "plan_resolution", plan_mock)
        monkeypatch.setattr(mod, "load_wofs_monthly_extent", Mock(return_value=_fake_extent([100])))
        monkeypatch.setattr(mod, "analyze_hydrological_state", Mock(return_value=_fake_state()))

        spec = _fake_spec(mod)
        result = mod.run_one_catchment(
            spec, force=False, resolution_override=None, allow_large=True, memory_budget_gb=1.0,
        )

        assert result["resolution_m"] == 30.0
        assert plan_mock.call_count == 2
        # bypass call used an effectively unlimited budget
        _, bypass_kwargs = plan_mock.call_args_list[1]
        assert bypass_kwargs["memory_budget_gb"] > 1e6

    def test_without_allow_large_native_no_fit_uses_gate_pick_as_is(self, mod, monkeypatch, tmp_path):
        monkeypatch.setattr(mod, "CATCHMENTS_DIR", tmp_path)
        monkeypatch.setattr(mod, "OUTPUT_DIR", tmp_path / "out")
        monkeypatch.setattr(mod, "_catchment_geo_summary", lambda key: _fake_geo())

        plan_mock = Mock(return_value=(300.0, 50.0, 0.001, "native_no_fit"))
        monkeypatch.setattr(mod, "probe_amplitude", Mock(return_value={
            "amplitude_pp": 5.0, "water_fraction_by_res": {}, "guard_caveat": None,
            "refuse_coarsen_past": None,
        }))
        monkeypatch.setattr(mod, "plan_resolution", plan_mock)
        monkeypatch.setattr(mod, "load_wofs_monthly_extent", Mock(return_value=_fake_extent([100])))
        monkeypatch.setattr(mod, "analyze_hydrological_state", Mock(return_value=_fake_state()))

        spec = _fake_spec(mod)
        result = mod.run_one_catchment(
            spec, force=False, resolution_override=None, allow_large=False, memory_budget_gb=1.0,
        )

        assert result["resolution_m"] == 300.0
        assert plan_mock.call_count == 1
        assert result["reason"] == "native_no_fit"


class TestSignalVetoStamping:
    def test_signal_veto_no_fit_still_processes_and_stamps_excluded(self, mod, monkeypatch, tmp_path):
        monkeypatch.setattr(mod, "CATCHMENTS_DIR", tmp_path)
        monkeypatch.setattr(mod, "OUTPUT_DIR", tmp_path / "out")
        monkeypatch.setattr(mod, "_catchment_geo_summary", lambda key: _fake_geo())

        probe_mock, plan_mock, load_mock, extent_mock, state_mock = _patch_common(
            mod, monkeypatch,
            plan_resolution_return=(100.0, 2.0, 0.5, "signal_veto_no_fit"),
        )

        spec = _fake_spec(mod)
        result = mod.run_one_catchment(
            spec, force=False, resolution_override=None, allow_large=False, memory_budget_gb=12.0,
        )

        # still fully processed -- load, extent, and state all ran.
        assert load_mock.called
        assert extent_mock.called
        assert state_mock.called
        assert result["pattern_claim_excluded"] is True
        assert result["reason"] == "signal_veto_no_fit"

    def test_non_veto_reason_leaves_pattern_claim_included(self, mod, monkeypatch, tmp_path):
        monkeypatch.setattr(mod, "CATCHMENTS_DIR", tmp_path)
        monkeypatch.setattr(mod, "OUTPUT_DIR", tmp_path / "out")
        monkeypatch.setattr(mod, "_catchment_geo_summary", lambda key: _fake_geo())

        _patch_common(mod, monkeypatch, plan_resolution_return=(30.0, 1.0, 0.001, "ok"))

        spec = _fake_spec(mod)
        result = mod.run_one_catchment(
            spec, force=False, resolution_override=None, allow_large=False, memory_budget_gb=12.0,
        )

        assert result["pattern_claim_excluded"] is False


class TestResultStamping:
    def test_result_dict_has_all_new_stamped_keys(self, mod, monkeypatch, tmp_path):
        monkeypatch.setattr(mod, "CATCHMENTS_DIR", tmp_path)
        monkeypatch.setattr(mod, "OUTPUT_DIR", tmp_path / "out")
        monkeypatch.setattr(mod, "_catchment_geo_summary", lambda key: _fake_geo())

        _patch_common(
            mod, monkeypatch,
            plan_resolution_return=(30.0, 1.0, 0.001, "ok"),
            n_valid=(90, 100, 110),
        )

        spec = _fake_spec(mod)
        result = mod.run_one_catchment(
            spec, force=False, resolution_override=None, allow_large=False, memory_budget_gb=12.0,
        )

        for key in (
            "resolution_m", "n_valid", "projected_noise_floor_pp", "reason",
            "guard_caveat", "pattern_claim_excluded",
        ):
            assert key in result, f"missing stamped key: {key}"

        # n_valid stamped as a single representative scalar (median across months),
        # not the whole per-month column.
        assert result["n_valid"] == 100  # median of (90, 100, 110)


class TestCheckpointSkipsReprobe:
    def test_checkpoint_hit_does_not_call_probe_or_plan_again(self, mod, monkeypatch, tmp_path):
        monkeypatch.setattr(mod, "CATCHMENTS_DIR", tmp_path)
        out_dir = tmp_path / "out"
        monkeypatch.setattr(mod, "OUTPUT_DIR", out_dir)
        monkeypatch.setattr(mod, "_catchment_geo_summary", lambda key: _fake_geo())

        probe_mock, plan_mock, load_mock, extent_mock, state_mock = _patch_common(
            mod, monkeypatch, plan_resolution_return=(30.0, 1.0, 0.001, "ok"),
        )

        spec = _fake_spec(mod)
        first = mod.run_one_catchment(
            spec, force=False, resolution_override=None, allow_large=False, memory_budget_gb=12.0,
        )
        assert probe_mock.call_count == 1
        assert plan_mock.call_count == 1

        # Second "run" against the now-existing checkpoint must not re-probe/re-plan,
        # and the checkpointed result already carries every new stamped key.
        second = mod.run_one_catchment(
            spec, force=False, resolution_override=None, allow_large=False, memory_budget_gb=12.0,
        )

        assert probe_mock.call_count == 1  # unchanged: no re-probe
        assert plan_mock.call_count == 1  # unchanged: no re-plan
        assert load_mock.call_count == 1  # unchanged: no re-load
        for key in ("resolution_m", "n_valid", "reason", "guard_caveat", "pattern_claim_excluded"):
            assert second[key] == first[key]

    def test_checkpoint_is_recomputed_when_date_range_changes(self, mod, monkeypatch, tmp_path):
        monkeypatch.setattr(mod, "CATCHMENTS_DIR", tmp_path)
        monkeypatch.setattr(mod, "OUTPUT_DIR", tmp_path / "out")
        monkeypatch.setattr(mod, "_catchment_geo_summary", lambda key: _fake_geo())
        probe_mock, _, load_mock, _, _ = _patch_common(
            mod, monkeypatch, plan_resolution_return=(30.0, 1.0, 0.001, "ok")
        )

        spec = _fake_spec(mod)
        mod.run_one_catchment(spec, force=False, end_date="2024-12-31")
        mod.run_one_catchment(spec, force=False, end_date="2025-12-31")

        assert probe_mock.call_count == 2
        assert load_mock.call_count == 2


class TestNoInteractivePrompt:
    def test_input_builtin_is_never_called(self, mod, monkeypatch, tmp_path):
        monkeypatch.setattr(mod, "CATCHMENTS_DIR", tmp_path)
        monkeypatch.setattr(mod, "OUTPUT_DIR", tmp_path / "out")
        monkeypatch.setattr(mod, "_catchment_geo_summary", lambda key: _fake_geo())

        def _boom(*a, **k):
            raise AssertionError("input() must never be called -- runner must stay non-interactive")

        monkeypatch.setattr("builtins.input", _boom)
        _patch_common(mod, monkeypatch, plan_resolution_return=(30.0, 1.0, 0.001, "ok"))

        spec = _fake_spec(mod)
        mod.run_one_catchment(
            spec, force=False, resolution_override=None, allow_large=False, memory_budget_gb=12.0,
        )
        # reaching here without the monkeypatched input() firing is the assertion.


def _synthetic_water_mask_cube(*, n_time=24, ny=8, nx=8, seed=0):
    """Build a real, small dask-backed water-mask cube with a seasonal cycle.

    Values use the canonical WOfS-style codes ``monthly_water_extent``
    expects: ``1`` (water), ``0`` (dry), ``-2`` (outside AOI, on a 1-pixel
    border so ``n_aoi`` and ``n_valid`` genuinely differ). The wet fraction
    is high in months 1-3, low in 7-9, and middling otherwise, so
    ``robust_scale``'s 10th-90th percentile amplitude is non-trivial and the
    whole real pipeline (prepare_monthly_extent -> robust_scale) has a
    meaningful signal to chew on, not a degenerate all-same-value series.
    """
    import dask.array as da
    import xarray as xr

    dates = pd.date_range("2015-01-01", periods=n_time, freq="MS")
    rng = np.random.default_rng(seed)
    data = np.empty((n_time, ny, nx), dtype=np.int8)
    for t in range(n_time):
        month = dates[t].month
        wet_frac = 0.7 if month in (1, 2, 3) else (0.15 if month in (7, 8, 9) else 0.4)
        data[t] = np.where(rng.random((ny, nx)) < wet_frac, 1, 0)
        data[t, 0, :] = -2
        data[t, :, 0] = -2

    arr = da.from_array(data, chunks=(4, ny, nx))
    return xr.DataArray(arr, dims=("time", "y", "x"), coords={"time": dates})


class TestRealWiredEndToEnd:
    """Exercises the real, wired-together gate/probe/reduction seam.

    Every other test in this file mocks ``probe_amplitude``/``plan_resolution``/
    ``monthly_water_extent`` directly, which means none of them would catch a
    genuine kwarg-name or return-shape mismatch between those real functions
    (each individually covered by its own unit tests, but never called
    together here). This test patches ONLY the actual network-touching
    ``load_wofs_from_stac`` -- in both the module under test (for the real
    load) and in ``hydroseason.io`` itself (for ``probe_amplitude``'s two
    internal probe/guard loads, since ``probe_amplitude`` resolves
    ``load_wofs_from_stac`` against its own module's namespace, not the
    runner script's) -- to return a small synthetic in-memory dask cube.
    ``plan_resolution``, ``probe_amplitude``, ``monthly_water_extent``, and
    ``_choose_resolution`` all run for real, so a real signature/kwarg
    mismatch between any pair of them would surface here.

    ``analyze_hydrological_state`` is still mocked: it is pattern/regime
    detection, explicitly out of scope for this plan's "extent feeder +
    runner only" scope guard, and already covered elsewhere.
    """

    def test_real_gate_probe_reduction_chain_wires_together(self, mod, monkeypatch, tmp_path):
        monkeypatch.setattr(mod, "CATCHMENTS_DIR", tmp_path)
        monkeypatch.setattr(mod, "OUTPUT_DIR", tmp_path / "out")
        monkeypatch.setattr(mod, "_catchment_geo_summary", lambda key: _fake_geo())
        monkeypatch.setattr(mod, "analyze_hydrological_state", Mock(return_value=_fake_state()))

        # Keep this integration slice to one year: probe_amplitude makes two
        # loads (probe + guard), plus one annual cached full-resolution load.
        monkeypatch.setattr(mod, "START_DATE", "2015-01-01")
        monkeypatch.setattr(mod, "END_DATE", "2015-12-31")
        (tmp_path / "test_catchment_boundary.geojson").write_text(
            '{"type":"FeatureCollection","features":[]}', encoding="utf-8"
        )
        cube = _synthetic_water_mask_cube(n_time=12)
        load_mock = Mock(return_value=cube)
        # probe_amplitude calls load_wofs_from_stac resolved in hydroseason.io's
        # own namespace -- patch it there, not just on the runner module.
        import hydroseason.io as hio
        monkeypatch.setattr(hio, "load_wofs_from_stac", load_mock)

        spec = _fake_spec(mod)
        result = mod.run_one_catchment(
            spec, force=False, resolution_override=None, allow_large=False,
            memory_budget_gb=12.0,
        )

        assert load_mock.call_count == 3

        # plan_resolution's real signal veto is a function of the AOI's tiny
        # (test-fixture) bounds and the real amplitude probe_amplitude computed
        # from the synthetic cube -- whatever it picked, it must be one of the
        # real candidate ladder's resolutions, and the stamped keys must be
        # internally consistent with each other (not just individually present).
        assert result["resolution_m"] in _DEFAULT_CANDIDATE_RES_M or result["reason"] == "native_no_fit"
        assert isinstance(result["projected_noise_floor_pp"], float)
        assert result["reason"] in {"ok", "coarsened", "signal_veto_no_fit", "native_no_fit"}
        assert result["pattern_claim_excluded"] == (result["reason"] == "signal_veto_no_fit")

        # n_valid was genuinely derived from monthly_water_extent's real counts
        # on the synthetic cube (8x8 grid minus a 1px AOI border -> 49 valid
        # pixels per timestep, all water/dry so none invalid).
        assert result["n_valid"] == 49


class TestCLIArgs:
    def test_argparse_accepts_new_flags(self, mod):
        parser_args = [
            "--resolution", "50",
            "--allow-large",
            "--memory-budget-gb", "8",
            "--workers", "3",
            "--time-block", "6",
            "--start-date", "2005-01-01",
            "--end-date", "2025-12-31",
        ]
        args = mod._build_arg_parser().parse_args(parser_args)
        assert args.resolution == 50.0
        assert args.allow_large is True
        assert args.memory_budget_gb == 8.0
        assert args.workers == 3
        assert args.time_block == 6
        assert args.start_date == "2005-01-01"
        assert args.end_date == "2025-12-31"

    def test_argparse_defaults(self, mod):
        args = mod._build_arg_parser().parse_args([])
        assert args.resolution is None
        assert args.allow_large is False
        assert args.memory_budget_gb == 12.0
        assert args.workers == 2
        assert args.time_block == 12


class TestParallelCatchments:
    def test_workers_overlap_and_results_keep_input_order(self, mod, monkeypatch):
        import threading

        lock = threading.Lock()
        two_active = threading.Event()
        active = 0
        peak = 0

        def fake_run(spec, **kwargs):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
                if active == 2:
                    two_active.set()
            assert two_active.wait(timeout=2)
            with lock:
                active -= 1
            return {"key": spec.key}

        monkeypatch.setattr(mod, "run_one_catchment", fake_run)
        specs = [_fake_spec(mod, key) for key in ("first", "second", "third")]

        results, failures = mod._run_catchments(
            specs, workers=2, run_kwargs={"force": False}
        )

        assert peak == 2
        assert [result["key"] for result in results] == ["first", "second", "third"]
        assert failures == []
