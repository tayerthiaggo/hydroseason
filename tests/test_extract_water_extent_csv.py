import argparse
import importlib.util
import sys
from pathlib import Path

import pytest


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
    assert args.offline is False
    assert args.legacy_remote_path is False


def test_offline_and_legacy_remote_are_mutually_exclusive(mod):
    with pytest.raises(SystemExit):
        mod._build_arg_parser().parse_args([
            "--aoi", "data/Gilbert_river_buffer.geojson", "--offline", "--legacy-remote-path"
        ])


def test_wet_mask_flag_defaults_off_and_accepts_dea_stats():
    import scripts.extract_water_extent_csv as script

    parser = script._build_arg_parser()

    assert parser.parse_args([]).wet_mask == "off"
    assert parser.parse_args(["--wet-mask", "dea_stats"]).wet_mask == "dea_stats"

    with pytest.raises(SystemExit):
        parser.parse_args(["--wet-mask", "nonsense"])


class _FakeExtent(list):
    """Minimal stand-in for the DataFrame `load_wofs_monthly_extent` returns:
    supports `len()` and a no-op `to_csv`, which is all `_process_job` needs
    before it reaches the `--profile` block under test.
    """

    def to_csv(self, *args, **kwargs):
        pass


class _FakeHandle:
    def __init__(self, path):
        self.path = path
        self.identity = "fake-identity"


def _make_args(tmp_path, wet_mask):
    return argparse.Namespace(
        resolution=30.0,
        output_csv=None,
        start_date="2015-01-01",
        end_date="2017-12-31",
        time_block=12,
        force=False,
        mask_cache_dir=tmp_path / "wofs_cache",
        legacy_remote_path=False,
        offline=False,
        read_workers=0,
        resampling_policy="categorical_safe",
        year_workers=1,
        wet_mask=wet_mask,
        profile=True,
    )


def _write_fake_manifest(handle_path: Path):
    handle_path.mkdir(parents=True, exist_ok=True)
    (handle_path / "manifest.json").write_text(
        '{"acquisition": {"plan_diagnostics": []}}', encoding="utf-8"
    )


def test_profile_block_does_not_touch_network_when_wet_mask_off(mod, tmp_path, monkeypatch):
    """With --wet-mask off, the profile block's offline acquire_wofs_cache call
    must receive wet_aoi=None and must never reach _resolve_wet_aoi's
    network-capable dea_stats branch (proven by making that branch raise).
    """

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("must not be called")

    monkeypatch.setattr(
        "hydroseason._io_wofs_acquire.fetch_dea_stats_wet_aoi", _must_not_be_called
    )

    monkeypatch.setattr(mod, "load_aoi", lambda path: "fake-aoi-gdf")
    monkeypatch.setattr(mod, "_aoi_digest", lambda aoi_gdf: "fake-aoi-digest")
    monkeypatch.setattr(mod, "load_wofs_monthly_extent", lambda *a, **k: _FakeExtent())

    offline_calls = []

    def _fake_acquire_wofs_cache(*args, **kwargs):
        offline_calls.append(kwargs)
        handle_path = tmp_path / "wofs_cache" / "store"
        _write_fake_manifest(handle_path)
        return _FakeHandle(handle_path)

    monkeypatch.setattr(mod, "acquire_wofs_cache", _fake_acquire_wofs_cache)

    args = _make_args(tmp_path, wet_mask="off")
    job = ("gilbert_river_qld", Path("data/catchments/gilbert_river_qld_boundary.geojson"))

    mod._process_job(job, args, tile_kwargs={})

    assert len(offline_calls) == 1
    assert "wet_aoi" in offline_calls[0]
    assert offline_calls[0]["wet_aoi"] is None
    assert offline_calls[0].get("offline") is True
    assert "wet_mask" not in offline_calls[0]


def test_profile_block_passes_resolved_wet_aoi_not_wet_mask(mod, tmp_path, monkeypatch):
    """With --wet-mask dea_stats, the profile block must resolve the wet mask
    itself (via _resolve_wet_aoi) and pass the RESOLVED wet_aoi to the offline
    acquire_wofs_cache call -- not pass wet_mask="dea_stats" straight through,
    which is the actual regression (offline=True can't resolve dea_stats
    itself and silently falls back to the unpruned store identity).
    """

    sentinel_wet_aoi = object()

    def _fake_resolve_wet_aoi(*args, **kwargs):
        return sentinel_wet_aoi, "fake-digest"

    monkeypatch.setattr(mod, "_resolve_wet_aoi", _fake_resolve_wet_aoi)
    monkeypatch.setattr(mod, "load_aoi", lambda path: "fake-aoi-gdf")
    monkeypatch.setattr(mod, "_aoi_digest", lambda aoi_gdf: "fake-aoi-digest")
    monkeypatch.setattr(
        mod, "_probe_local_wet_aoi_handle", lambda *a, **k: None
    )
    monkeypatch.setattr(mod, "load_wofs_monthly_extent", lambda *a, **k: _FakeExtent())

    offline_calls = []

    def _fake_acquire_wofs_cache(*args, **kwargs):
        offline_calls.append(kwargs)
        handle_path = tmp_path / "wofs_cache" / "store"
        _write_fake_manifest(handle_path)
        return _FakeHandle(handle_path)

    monkeypatch.setattr(mod, "acquire_wofs_cache", _fake_acquire_wofs_cache)

    args = _make_args(tmp_path, wet_mask="dea_stats")
    job = ("gilbert_river_qld", Path("data/catchments/gilbert_river_qld_boundary.geojson"))

    mod._process_job(job, args, tile_kwargs={})

    assert len(offline_calls) == 1
    assert offline_calls[0].get("wet_aoi") is sentinel_wet_aoi
    assert "wet_mask" not in offline_calls[0]


def test_profile_block_passes_local_wet_aoi_handle_from_existing_store(mod, tmp_path, monkeypatch):
    """When a completed unpruned local store already exists for this AOI/date
    range, the profile block's own _resolve_wet_aoi call must be handed the
    SAME local_wet_aoi_handle the main (non-profile) acquire_wofs_cache call
    would have found -- otherwise the profile block's mask resolution can
    fall through to the dea_stats network branch and diverge from what the
    main call actually wrote (a narrower repeat of the f69ab09 bug).

    Simulates the probe by monkeypatching the module-level hook the profile
    block must use to look up the existing local store, and asserts the
    exact same handle object flows through into the local_wet_aoi_handle
    kwarg of the _resolve_wet_aoi call.
    """

    sentinel_handle = _FakeHandle(tmp_path / "wofs_cache" / "existing-unpruned-store")

    def _fake_probe_local_wet_aoi_handle(*args, **kwargs):
        return sentinel_handle

    monkeypatch.setattr(
        mod, "_probe_local_wet_aoi_handle", _fake_probe_local_wet_aoi_handle
    )
    monkeypatch.setattr(mod, "load_aoi", lambda path: "fake-aoi-gdf")
    monkeypatch.setattr(mod, "_aoi_digest", lambda aoi_gdf: "fake-aoi-digest")
    monkeypatch.setattr(mod, "load_wofs_monthly_extent", lambda *a, **k: _FakeExtent())

    resolve_calls = []

    def _fake_resolve_wet_aoi(*args, **kwargs):
        resolve_calls.append(kwargs)
        return object(), "fake-digest"

    monkeypatch.setattr(mod, "_resolve_wet_aoi", _fake_resolve_wet_aoi)

    def _fake_acquire_wofs_cache(*args, **kwargs):
        handle_path = tmp_path / "wofs_cache" / "store"
        _write_fake_manifest(handle_path)
        return _FakeHandle(handle_path)

    monkeypatch.setattr(mod, "acquire_wofs_cache", _fake_acquire_wofs_cache)

    args = _make_args(tmp_path, wet_mask="dea_stats")
    job = ("gilbert_river_qld", Path("data/catchments/gilbert_river_qld_boundary.geojson"))

    mod._process_job(job, args, tile_kwargs={})

    assert len(resolve_calls) == 1
    assert resolve_calls[0].get("local_wet_aoi_handle") is sentinel_handle
