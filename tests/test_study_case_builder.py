from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from scripts._build_study_case_offline import CATCHMENT_NAMES, build_main_study
from scripts._build_study_case_rainfall import build_rainfall_study
from scripts._scientific_baseline_guard import PROTECTED_BASELINE

REPO_ROOT = Path(__file__).resolve().parent.parent
CASE_DATA = REPO_ROOT / "case_studies" / "data" / "extent"
RAINFALL_DATA = REPO_ROOT / "case_studies" / "data" / "rainfall"


def test_main_study_uses_committed_30m_inputs_and_respects_routes(tmp_path: Path):
    summary = build_main_study(CASE_DATA, tmp_path)
    assert summary["key"].tolist() == sorted(CATCHMENT_NAMES.keys())
    assert summary["series_used"].eq("extent_pct").all()

    dry = summary.set_index("key").loc[
        ["lachlan_river_nsw", "moonie_river_qld_nsw"]
    ]
    assert dry["route"].eq("event_characterisation").all()
    assert dry["n_hydro_years"].eq(0).all()

    for key in dry.index:
        years_csv = tmp_path / key / f"{key}_hydro_years.csv"
        if not years_csv.exists():
            years_csv = tmp_path / key / f"{key.replace('_', '-')}_hydro_years.csv"
        years = pd.read_csv(years_csv)
        assert years.empty


def test_builder_never_reads_ignored_output_tree(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    summary = build_main_study(CASE_DATA, tmp_path / "generated")
    assert len(summary) == 5


def test_main_builder_refuses_protected_scientific_baseline():
    with pytest.raises(ValueError, match="protected scientific baseline"):
        build_main_study(CASE_DATA, PROTECTED_BASELINE)


def test_rainfall_builder_refuses_protected_scientific_baseline():
    with pytest.raises(ValueError, match="protected scientific baseline"):
        build_rainfall_study(CASE_DATA, RAINFALL_DATA, PROTECTED_BASELINE)
