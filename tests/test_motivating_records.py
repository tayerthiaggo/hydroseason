from __future__ import annotations

from pathlib import Path

import pytest

from hydroseason._catchment import analyze_catchment
from scripts.check_motivating_records import (
    check_denison,
    check_nebo,
    check_taroom,
    find_bundle,
    load_observation_frame,
    run_check,
)

STRESS_ROOT = Path(r"D:\RLH\5.6\hydroseason_tests\outputs\stress_test_final")

pytestmark = pytest.mark.skipif(
    not STRESS_ROOT.exists(),
    reason="external stress-test bundle not available on this machine",
)


def _analysis(station_id: str):
    bundle_dir = find_bundle(STRESS_ROOT, station_id)
    observations = load_observation_frame(bundle_dir)
    return analyze_catchment(observations)


def test_denison_creek_at_braeside_qualitative_behaviour():
    analysis = _analysis("130413a")
    results = check_denison(analysis)
    assert results["n_zero_months"] > 0
    assert results["pixel_support_status"] == "unavailable"


def test_nebo_creek_at_nebo_qualitative_behaviour():
    analysis = _analysis("130407a")
    results = check_nebo(analysis)
    assert results["timing_evidence"] == "insufficient"
    assert results["route"] == "event_characterisation"
    assert analysis.hydro_years.empty


def test_dawson_river_at_taroom_qualitative_behaviour():
    analysis = _analysis("130302a")
    results = check_taroom(analysis)
    assert results["n_events"] > 0
    assert results["pixel_support_status"] == "unavailable"


def test_all_three_motivating_records_report_pixel_support_unavailable():
    """Every motivating record is percentage-only, so min_peak_water_pixels is
    not consulted for any of them -- assert this explicitly so a future
    count-bearing input does not silently change what this check means."""
    for station_id in ("130413a", "130407a", "130302a"):
        analysis = _analysis(station_id)
        assert analysis.regime.pixel_support_status == "unavailable"


def test_run_check_matches_station_ids_case_insensitively():
    report = run_check(STRESS_ROOT, "130413A")
    assert report["passed"] is True
    assert report["station_id"] == "130413a"


def test_run_check_raises_for_unregistered_station():
    with pytest.raises(ValueError, match="no motivating-record check registered"):
        run_check(STRESS_ROOT, "999999z")
