import json

import numpy as np
import pandas as pd
import pytest

from scripts.build_final_review import (
    REVIEW_CATCHMENTS,
    _run_stage,
    build_index,
    input_hashes,
    load_review_inputs,
    run_cases,
)


def _seasonal_series(years: int = 6, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    cycle = 1.0 + 0.8 * np.cos(2 * np.pi * (np.arange(12) - 1) / 12)
    index = pd.date_range("2005-01-01", periods=12 * years, freq="MS")
    values = np.tile(cycle, years) + rng.normal(0, 0.02, 12 * years)
    return pd.DataFrame(
        {"extent_pct": np.clip(values, 0, None), "invalid_pct": 0.0}, index=index
    )


def _aseasonal_series(years: int = 6, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    index = pd.date_range("2005-01-01", periods=12 * years, freq="MS")
    values = np.abs(rng.normal(0.15, 0.12, 12 * years))
    return pd.DataFrame({"extent_pct": values, "invalid_pct": 0.0}, index=index)


def _write_synthetic_manifest(data_root, frames: dict[str, pd.DataFrame]) -> None:
    import hashlib

    extent_dir = data_root / "extent"
    extent_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"inputs": {}}
    for key, frame in frames.items():
        rel = f"extent/{key}_30m.csv"
        path = data_root / rel
        out = frame.copy()
        out.index.name = "date"
        out.to_csv(path)
        manifest["inputs"][f"{key}_30m"] = {
            "catchment": key,
            "resolution_m": 30,
            "file": rel,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    (data_root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_load_review_inputs_verifies_hashes(tmp_path):
    frames = {key: _seasonal_series(years=3, seed=i) for i, key in enumerate(REVIEW_CATCHMENTS)}
    data_root = tmp_path / "data"
    _write_synthetic_manifest(data_root, frames)

    loaded = load_review_inputs(data_root)
    assert set(loaded) == set(REVIEW_CATCHMENTS)
    for key in REVIEW_CATCHMENTS:
        pd.testing.assert_series_equal(
            loaded[key]["extent_pct"],
            frames[key]["extent_pct"],
            check_names=False,
            check_freq=False,
        )


def test_load_review_inputs_refuses_hash_mismatch(tmp_path):
    frames = {key: _seasonal_series(years=3, seed=i) for i, key in enumerate(REVIEW_CATCHMENTS)}
    data_root = tmp_path / "data"
    _write_synthetic_manifest(data_root, frames)

    tampered_path = data_root / "extent" / f"{REVIEW_CATCHMENTS[0]}_30m.csv"
    tampered_path.write_text(tampered_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        load_review_inputs(data_root)


def test_load_review_inputs_refuses_missing_entry(tmp_path):
    frames = {key: _seasonal_series(years=3, seed=i) for i, key in enumerate(REVIEW_CATCHMENTS)}
    data_root = tmp_path / "data"
    _write_synthetic_manifest(data_root, frames)

    manifest_path = data_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["inputs"][f"{REVIEW_CATCHMENTS[0]}_30m"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="no entry"):
        load_review_inputs(data_root)


def test_run_cases_writes_reports_and_full_tables(tmp_path):
    frames = {"seasonal_case": _seasonal_series(years=6)}
    results = run_cases(frames, output_dir=tmp_path / "cases", refinement_policy=None)

    case = results["seasonal_case"]
    assert case["status"] == "ok"
    for name in ("hydro_years", "monthly", "events", "low_spells"):
        assert isinstance(case[name], pd.DataFrame)
    case_dir = tmp_path / "cases" / "seasonal_case"
    assert (case_dir / "full_hydro_years.csv").exists()
    assert (case_dir / "full_monthly.csv").exists()
    assert (case_dir / "full_events.csv").exists()
    assert (case_dir / "full_low_spells.csv").exists()
    assert (case_dir / "seasonal-case.html").exists()


def test_run_cases_marks_refinement_not_run_for_event_route(tmp_path):
    from hydroseason._trough_refinement import TroughRefinementPolicy

    frames = {"aseasonal_case": _aseasonal_series(years=6)}
    policy = TroughRefinementPolicy(huber_k=1.345, profile_loss_cutoff=0.05, pulse_z=1.5)
    results = run_cases(frames, output_dir=tmp_path / "cases", refinement_policy=policy)

    case = results["aseasonal_case"]
    assert case["route"] == "event_characterisation"
    assert case["status"] == "not_run_for_event_route"
    assert case["refinement_applicable"] is False


def test_run_cases_records_failed_case_without_aborting_run(tmp_path):
    frames = {
        "good": _seasonal_series(years=6, seed=1),
        "bad": "not a dataframe",
    }
    results = run_cases(frames, output_dir=tmp_path / "cases", refinement_policy=None)

    assert results["good"]["status"] == "ok"
    assert results["bad"]["status"] == "failed"
    assert "error" in results["bad"]


def test_baseline_stage_is_immutable_and_refuses_hash_mismatch(tmp_path, monkeypatch):
    import scripts.build_final_review as bfr

    frames = {key: _seasonal_series(years=4, seed=i) for i, key in enumerate(REVIEW_CATCHMENTS)}
    data_root = tmp_path / "data"
    _write_synthetic_manifest(data_root, frames)
    monkeypatch.setattr(bfr, "DATA_ROOT", data_root)

    output_dir = tmp_path / "bundle"
    exit_code = _run_stage("before", output_dir)
    assert exit_code == 0
    manifest_path = output_dir / "before" / "manifest.json"
    assert manifest_path.exists()
    first_manifest = manifest_path.read_text(encoding="utf-8")
    recorded_hashes = json.loads(first_manifest)["input_hashes"]
    assert recorded_hashes == input_hashes(data_root)

    # Re-running against identical inputs must be a no-op (idempotent reuse).
    exit_code_again = _run_stage("before", output_dir)
    assert exit_code_again == 0
    assert manifest_path.read_text(encoding="utf-8") == first_manifest

    # Changing an input (and its own manifest hash, so load_review_inputs
    # itself still accepts it) must not silently rewrite the frozen baseline.
    changed_key = REVIEW_CATCHMENTS[0]
    changed_path = data_root / "extent" / f"{changed_key}_30m.csv"
    new_frame = _seasonal_series(years=4, seed=99)
    new_frame.index.name = "date"
    new_frame.to_csv(changed_path)
    import hashlib

    source_manifest_path = data_root / "manifest.json"
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    source_manifest["inputs"][f"{changed_key}_30m"]["sha256"] = hashlib.sha256(
        changed_path.read_bytes()
    ).hexdigest()
    source_manifest_path.write_text(json.dumps(source_manifest), encoding="utf-8")

    with pytest.raises(SystemExit, match="refusing to overwrite"):
        _run_stage("before", output_dir)
    assert manifest_path.read_text(encoding="utf-8") == first_manifest


def test_build_index_links_case_reports(tmp_path, monkeypatch):
    import scripts.build_final_review as bfr

    frames = {key: _seasonal_series(years=4, seed=i) for i, key in enumerate(REVIEW_CATCHMENTS)}
    data_root = tmp_path / "data"
    _write_synthetic_manifest(data_root, frames)
    monkeypatch.setattr(bfr, "DATA_ROOT", data_root)

    output_dir = tmp_path / "bundle"
    _run_stage("before", output_dir)
    index_path = build_index(output_dir)

    assert index_path.exists()
    text = index_path.read_text(encoding="utf-8")
    for key in REVIEW_CATCHMENTS:
        assert key in text


def _run_after_stage_on_synthetic_inputs(tmp_path, monkeypatch):
    import scripts.build_final_review as bfr

    frames = {key: _seasonal_series(years=4, seed=i) for i, key in enumerate(REVIEW_CATCHMENTS)}
    data_root = tmp_path / "data"
    _write_synthetic_manifest(data_root, frames)
    monkeypatch.setattr(bfr, "DATA_ROOT", data_root)

    output_dir = tmp_path / "bundle"
    exit_code = _run_stage("after", output_dir)
    return output_dir, exit_code


def _iter_local_links(html_text: str) -> list[str]:
    import re

    return [
        href
        for href in re.findall(r'href="([^"]+)"', html_text)
        if not href.startswith(("http://", "https://", "#", "data:", "mailto:"))
    ]


def test_after_stage_produces_smoke_comparisons_and_review_notes(tmp_path, monkeypatch):
    output_dir, exit_code = _run_after_stage_on_synthetic_inputs(tmp_path, monkeypatch)

    assert exit_code == 0
    assert (output_dir / "smoke" / "index.html").exists()
    assert (output_dir / "review-notes.md").exists()
    assert (output_dir / "comparisons" / "catchments.csv").exists()
    assert (output_dir / "comparisons" / "cycles.csv").exists()
    assert (output_dir / "comparisons" / "months.csv").exists()
    assert (output_dir / "manifest.json").exists()

    review_notes = (output_dir / "review-notes.md").read_text(encoding="utf-8")
    for key in REVIEW_CATCHMENTS:
        assert key in review_notes

    # All nine smoke cases produced a case directory (report or failure).
    smoke_manifest = json.loads((output_dir / "after" / "manifest.json").read_text(encoding="utf-8"))
    assert len(smoke_manifest["smoke"]) == 9


def test_every_internal_link_in_the_bundle_resolves(tmp_path, monkeypatch):
    output_dir, _ = _run_after_stage_on_synthetic_inputs(tmp_path, monkeypatch)

    checked = 0
    for html_path in output_dir.rglob("*.html"):
        text = html_path.read_text(encoding="utf-8")
        for href in _iter_local_links(text):
            target = (html_path.parent / href).resolve()
            assert target.exists(), f"{html_path} links to missing {href}"
            checked += 1
    assert checked > 0


def test_every_generated_report_has_its_four_csv_siblings(tmp_path, monkeypatch):
    output_dir, _ = _run_after_stage_on_synthetic_inputs(tmp_path, monkeypatch)

    checked = 0
    for html_path in output_dir.rglob("*.html"):
        if html_path.name in {"index.html"}:
            continue
        stem = html_path.stem
        case_dir = html_path.parent
        for suffix in ("_hydro_years.csv", "_low_spells.csv", "_monthly.csv", "_wet_event.csv"):
            assert (case_dir / f"{stem}{suffix}").exists(), f"{html_path} missing {suffix}"
        checked += 1
    assert checked > 0


def test_after_stage_preserves_all_five_input_hashes(tmp_path, monkeypatch):
    output_dir, _ = _run_after_stage_on_synthetic_inputs(tmp_path, monkeypatch)

    after_manifest = json.loads((output_dir / "after" / "manifest.json").read_text(encoding="utf-8"))
    assert len(after_manifest["input_hashes"]) == len(REVIEW_CATCHMENTS)
    assert set(after_manifest["input_hashes"]) == set(REVIEW_CATCHMENTS)


def test_run_stage_reports_nonzero_exit_and_failed_case_after_an_exception(tmp_path, monkeypatch):
    """A failed case must not abort the run: remaining cases still complete,
    and the runner exits nonzero so the failure cannot be missed.
    """
    import scripts.build_final_review as bfr

    frames = {key: _seasonal_series(years=4, seed=i) for i, key in enumerate(REVIEW_CATCHMENTS)}
    data_root = tmp_path / "data"
    _write_synthetic_manifest(data_root, frames)
    monkeypatch.setattr(bfr, "DATA_ROOT", data_root)

    real_load = bfr.load_review_inputs

    def _poisoned_load(data_root_arg):
        loaded = real_load(data_root_arg)
        loaded[REVIEW_CATCHMENTS[0]] = "not a dataframe"
        return loaded

    monkeypatch.setattr(bfr, "load_review_inputs", _poisoned_load)

    output_dir = tmp_path / "bundle"
    exit_code = _run_stage("before", output_dir)

    assert exit_code == 1
    manifest = json.loads((output_dir / "before" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["cases"]["default"][REVIEW_CATCHMENTS[0]]["status"] == "failed"
    # Every other catchment still completed despite the poisoned one.
    for key in REVIEW_CATCHMENTS[1:]:
        assert manifest["cases"]["default"][key]["status"] == "ok"


def test_make_smoke_frames_returns_nine_complete_monthly_cases():
    from scripts.build_final_review import make_smoke_frames

    frames = make_smoke_frames()
    assert len(frames) == 9
    for name, frame in frames.items():
        assert len(frame) == 180, name
        assert frame.index.freqstr in {"MS", None}
        assert (frame["extent_pct"].dropna() >= 0).all()
        assert (frame["extent_pct"].dropna() <= 100).all()


def test_smoke_flat_records_do_not_force_seasonal_processing(tmp_path):
    from hydroseason._trough_refinement import TroughRefinementPolicy
    from scripts.build_final_review import make_smoke_frames, run_cases

    frames = make_smoke_frames()
    flat = {key: frames[key] for key in ("all-zero", "constant-water")}
    policy = TroughRefinementPolicy(huber_k=1.345, profile_loss_cutoff=0.05, pulse_z=1.5)
    results = run_cases(flat, output_dir=tmp_path / "smoke", refinement_policy=policy)

    for key, case in results.items():
        assert case["status"] != "failed", key
        assert case["route"] == "event_characterisation", key
        assert case["hydro_years"].empty, key
