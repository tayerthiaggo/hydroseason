import importlib.util
import sys
from pathlib import Path

import pytest

pytest.importorskip("affine")


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "extract_water_extent_csv.py"


@pytest.fixture()
def mod():
    spec = importlib.util.spec_from_file_location("extract_water_extent_csv_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


def test_parser_defaults_to_30m_canonical_cache(mod):
    args = mod._build_arg_parser().parse_args(["--aoi", "data/Gilbert_river_buffer.geojson"])

    assert args.resolution == 30.0
    assert args.end_date == "2025-12-01"
    assert args.offline is False
    assert args.legacy_remote_path is False
    assert args.full_aoi is False


def test_parser_accepts_explicit_full_aoi_compatibility_mode(mod):
    args = mod._build_arg_parser().parse_args(["--full-aoi"])

    assert args.full_aoi is True


def test_offline_and_legacy_remote_are_mutually_exclusive(mod):
    with pytest.raises(SystemExit):
        mod._build_arg_parser().parse_args([
            "--aoi", "data/Gilbert_river_buffer.geojson", "--offline", "--legacy-remote-path"
        ])


def test_parser_does_not_expose_legacy_wet_mask_modes(mod):
    args = mod._build_arg_parser().parse_args([])

    assert not hasattr(args, "wet_mask")
    with pytest.raises(SystemExit):
        mod._build_arg_parser().parse_args(["--wet-mask", "dea_stats"])


class _FakeExtent(list):
    """Minimal stand-in for the DataFrame `load_wofs_monthly_extent` returns:
    supports `len()` and a no-op `to_csv`, which is all `_process_job` needs.
    """

    def to_csv(self, *args, **kwargs):
        pass


def test_default_process_uses_high_level_historical_mask_workflow(mod, monkeypatch):
    calls = []

    def _fake_load(*args, **kwargs):
        calls.append(kwargs)
        return _FakeExtent()

    monkeypatch.setattr(mod, "load_wofs_monthly_extent", _fake_load)
    args = mod._build_arg_parser().parse_args([])

    mod._process_job(("example", Path("example.geojson")), args, tile_kwargs={})

    assert calls[0]["use_historical_water_mask"] is True


def test_full_aoi_process_uses_explicit_compatibility_mode(mod, monkeypatch):
    calls = []

    def _fake_load(*args, **kwargs):
        calls.append(kwargs)
        return _FakeExtent()

    monkeypatch.setattr(mod, "load_wofs_monthly_extent", _fake_load)
    args = mod._build_arg_parser().parse_args(["--full-aoi"])

    mod._process_job(("example", Path("example.geojson")), args, tile_kwargs={})

    assert calls[0]["use_historical_water_mask"] is False


def test_offline_historical_mask_cache_failure_is_not_downgraded(mod, monkeypatch):
    from hydroseason._io_dea_stats import DEAStatsUnavailable

    calls = []

    def _offline_cache_miss(*args, **kwargs):
        calls.append(kwargs)
        raise DEAStatsUnavailable("no cached historical water mask")

    monkeypatch.setattr(mod, "load_wofs_monthly_extent", _offline_cache_miss)
    args = mod._build_arg_parser().parse_args(["--offline"])

    with pytest.raises(DEAStatsUnavailable, match="no cached historical water mask"):
        mod._process_job(("example", Path("example.geojson")), args, tile_kwargs={})

    assert len(calls) == 1
    assert calls[0]["offline"] is True
    assert calls[0]["use_historical_water_mask"] is True
