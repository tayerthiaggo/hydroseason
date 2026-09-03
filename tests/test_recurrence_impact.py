import numpy as np
import pandas as pd

from scripts.audit_recurrence_impact import (
    compare_annual_rows,
    compare_record_fields,
)


def test_compare_annual_rows_reports_every_public_timing_change():
    legacy = pd.DataFrame({
        "hy_year": [2001],
        "peak_timing_status": ["point"],
        "trough_timing_status": ["point"],
        "trough_interval_start": ["2001-10-01"],
        "trough_interval_end": ["2001-10-01"],
        "timing_status": ["point"],
        "status_reason": ["ok"],
        "baseline_uncertain": [False],
    })
    selected = legacy.copy()
    selected.loc[0, ["trough_timing_status", "timing_status", "status_reason", "baseline_uncertain"]] = [
        "unresolved", "unresolved", "unresolved_timing", True,
    ]
    changes = compare_annual_rows("station-a", legacy, selected)
    assert changes == [{
        "station_id": "station-a",
        "hy_year": 2001,
        "field": "trough_timing_status",
        "legacy": "point",
        "selected": "unresolved",
    }, {
        "station_id": "station-a",
        "hy_year": 2001,
        "field": "timing_status",
        "legacy": "point",
        "selected": "unresolved",
    }, {
        "station_id": "station-a",
        "hy_year": 2001,
        "field": "status_reason",
        "legacy": "ok",
        "selected": "unresolved_timing",
    }, {
        "station_id": "station-a",
        "hy_year": 2001,
        "field": "baseline_uncertain",
        "legacy": False,
        "selected": True,
    }]


def test_compare_annual_rows_unchanged_year_produces_no_diff():
    legacy = pd.DataFrame({
        "hy_year": [2001, 2002],
        "peak_timing_status": ["point", "interval"],
        "trough_timing_status": ["point", "point"],
        "timing_status": ["point", "interval"],
        "status_reason": ["ok", "ok"],
        "boundary_status": ["confirmed", "confirmed"],
        "confidence": ["high", "high"],
        "baseline_uncertain": [False, False],
    })
    selected = legacy.copy()
    selected.loc[1, "timing_status"] = "unresolved"
    changes = compare_annual_rows("station-b", legacy, selected)
    assert len(changes) == 1
    assert changes[0] == {
        "station_id": "station-b",
        "hy_year": 2002,
        "field": "timing_status",
        "legacy": "interval",
        "selected": "unresolved",
    }


def test_compare_annual_rows_normalizes_dates_and_scalars():
    legacy = pd.DataFrame({
        "hy_year": [np.int64(2005)],
        "peak_interval_start_date": ["2005-07-01"],
        "baseline_uncertain": [np.bool_(False)],
    })
    selected = pd.DataFrame({
        "hy_year": [2005],
        "peak_interval_start": [pd.Timestamp("2005-07-01")],
        "baseline_uncertain": [False],
    })
    changes = compare_annual_rows("station-c", legacy, selected)
    assert changes == []


def test_compare_record_fields_detects_changes():
    legacy = {"route": "per_year_detection", "publication_category": "point_supported"}
    selected = {"route": "event_characterisation", "publication_category": "event_only"}
    changes = compare_record_fields("station-d", legacy, selected)
    assert changes == [
        {
            "station_id": "station-d",
            "field": "route",
            "legacy": "per_year_detection",
            "selected": "event_characterisation",
        },
        {
            "station_id": "station-d",
            "field": "publication_category",
            "legacy": "point_supported",
            "selected": "event_only",
        },
    ]
