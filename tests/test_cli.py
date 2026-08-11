import json
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

from hydroseason import cli


def _extent_csv(path):
    dates = pd.date_range("2010-01-01", periods=96, freq="MS")
    phase = 2 * np.pi * (dates.month - 2) / 12
    pd.DataFrame(
        {
            "date": dates,
            "extent_pct": np.clip(35 + 25 * np.cos(phase), 0, 100),
            "invalid_pct": 0.0,
        }
    ).to_csv(path, index=False)
    return path


def test_run_maps_every_documented_argument_to_one_orchestrator_call(
    monkeypatch, tmp_path
):
    """The CLI must not reimplement anything: exactly one run_hydroseason
    call, with path/scalar arguments translated verbatim."""
    calls = []

    def fake_run(water_source=None, **kwargs):
        calls.append((water_source, kwargs))
        return _FakeResult(tmp_path)

    monkeypatch.setattr("hydroseason.cli.run_hydroseason", fake_run)
    exit_code = cli.main(
        [
            "run",
            "--water-source", "extent.csv",
            "--output-dir", str(tmp_path / "out"),
            "--aoi", "aoi.geojson",
            "--aoi-name", "Isaac River",
            "--start-date", "2005-01-01",
            "--end-date", "2025-12-01",
            "--water-mask-variable", "water_mask",
            "--rainfall-csv", "rain.csv",
            "--stac-url", "https://example.test/stac",
            "--statistics-stac-url", "https://stats.test/stac",
            "--stac-collection", "ga_ls_wo_3",
            "--cache-dir", str(tmp_path / "cache"),
            "--report-title", "Title",
            "--report-subtitle", "Subtitle",
        ]
    )

    assert exit_code == 0
    assert len(calls) == 1
    water_source, kwargs = calls[0]
    assert water_source == "extent.csv"
    assert kwargs["output_dir"] == str(tmp_path / "out")
    assert kwargs["aoi"] == "aoi.geojson"
    assert kwargs["aoi_name"] == "Isaac River"
    assert kwargs["start_date"] == "2005-01-01"
    assert kwargs["end_date"] == "2025-12-01"
    assert kwargs["water_mask_variable"] == "water_mask"
    assert kwargs["rainfall_csv_path"] == "rain.csv"
    assert kwargs["fetch_rainfall"] is False
    assert kwargs["stac_url"] == "https://example.test/stac"
    assert kwargs["statistics_stac_url"] == "https://stats.test/stac"
    assert kwargs["stac_collection"] == "ga_ls_wo_3"
    assert kwargs["cache_dir"] == str(tmp_path / "cache")
    assert kwargs["report_title"] == "Title"
    assert kwargs["report_subtitle"] == "Subtitle"


def test_omitted_water_source_leaves_the_dea_fetch_path_selected(
    monkeypatch, tmp_path
):
    calls = []

    def fake_run(water_source=None, **kwargs):
        calls.append(water_source)
        return _FakeResult(tmp_path)

    monkeypatch.setattr("hydroseason.cli.run_hydroseason", fake_run)
    cli.main(
        [
            "run", "--output-dir", str(tmp_path), "--aoi", "aoi.geojson",
            "--start-date", "2005-01-01", "--end-date", "2025-12-01",
        ]
    )

    assert calls == [None]


def test_progress_is_on_by_default_and_can_be_disabled(monkeypatch, tmp_path):
    seen = []

    def fake_run(water_source=None, **kwargs):
        seen.append(kwargs["progress"])
        return _FakeResult(tmp_path)

    monkeypatch.setattr("hydroseason.cli.run_hydroseason", fake_run)
    cli.main(["run", "--water-source", "e.csv", "--output-dir", str(tmp_path)])
    cli.main(
        [
            "run", "--no-progress", "--water-source", "e.csv",
            "--output-dir", str(tmp_path),
        ]
    )

    assert seen == [True, False]


def test_fatal_orchestrator_failure_returns_nonzero(monkeypatch, tmp_path, capsys):
    def explode(*args, **kwargs):
        raise RuntimeError("statistics endpoint unreachable")

    monkeypatch.setattr("hydroseason.cli.run_hydroseason", explode)
    exit_code = cli.main(
        ["run", "--water-source", "e.csv", "--output-dir", str(tmp_path)]
    )

    assert exit_code == 1
    assert "statistics endpoint unreachable" in capsys.readouterr().err


def test_ancillary_rainfall_failure_still_succeeds(monkeypatch, tmp_path, capsys):
    """run_hydroseason treats rainfall as best-effort; the CLI must not turn
    that into a nonzero exit."""

    def fake_run(water_source=None, **kwargs):
        return _FakeResult(tmp_path, rainfall_status="fetch_failed")

    monkeypatch.setattr("hydroseason.cli.run_hydroseason", fake_run)
    exit_code = cli.main(
        ["run", "--water-source", "e.csv", "--output-dir", str(tmp_path)]
    )

    assert exit_code == 0
    assert "fetch_failed" in capsys.readouterr().out


def test_summary_reports_source_regime_route_rainfall_and_paths(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setattr(
        "hydroseason.cli.run_hydroseason",
        lambda water_source=None, **kwargs: _FakeResult(tmp_path),
    )
    cli.main(["run", "--water-source", "e.csv", "--output-dir", str(tmp_path)])

    out = capsys.readouterr().out
    for expected in (
        "extent_csv",
        "seasonal",
        "per_year_detection",
        "disabled",
        "report.html",
        "monthly.csv",
        "years.csv",
        "events.csv",
        "spells.csv",
    ):
        assert expected in out


def test_json_summary_is_machine_readable(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        "hydroseason.cli.run_hydroseason",
        lambda water_source=None, **kwargs: _FakeResult(tmp_path),
    )
    cli.main(
        ["run", "--json", "--water-source", "e.csv", "--output-dir", str(tmp_path)]
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["source_kind"] == "extent_csv"
    assert payload["rainfall_status"] == "disabled"
    assert payload["html"].endswith("report.html")


def test_end_to_end_csv_run_writes_the_bundle(tmp_path):
    """No mocks: the real orchestrator on a real CSV, through the CLI."""
    csv_path = _extent_csv(tmp_path / "extent.csv")
    out_dir = tmp_path / "out"

    exit_code = cli.main(
        [
            "run", "--water-source", str(csv_path),
            "--output-dir", str(out_dir), "--aoi-name", "CLI AOI",
            "--no-progress",
        ]
    )

    assert exit_code == 0
    assert list(out_dir.glob("*.html"))


def test_help_exits_zero():
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--help"])

    assert excinfo.value.code == 0


def test_run_help_exits_zero():
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["run", "--help"])

    assert excinfo.value.code == 0


def test_python_m_hydroseason_help_smoke():
    completed = subprocess.run(
        [sys.executable, "-m", "hydroseason", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "{run,doctor}" in completed.stdout


def test_unknown_argument_is_a_usage_error():
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["run", "--nope"])

    assert excinfo.value.code == 2


def test_version_reports_the_package_version(capsys):
    import hydroseason

    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--version"])

    assert excinfo.value.code == 0
    assert hydroseason.__version__ in capsys.readouterr().out


def test_doctor_lists_checks_and_exits_nonzero_on_error(monkeypatch, capsys):
    from hydroseason._diagnostics import EnvironmentCheck

    monkeypatch.setattr(
        "hydroseason.cli.check_environment",
        lambda **kwargs: (
            EnvironmentCheck("python", "ok", "3.12.4"),
            EnvironmentCheck("s3fs", "error", "No module named 's3fs'"),
        ),
    )
    exit_code = cli.main(["doctor"])

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "python" in out and "3.12.4" in out
    assert "s3fs" in out and "No module named" in out


def test_doctor_exits_zero_when_everything_is_ok(monkeypatch):
    from hydroseason._diagnostics import EnvironmentCheck

    monkeypatch.setattr(
        "hydroseason.cli.check_environment",
        lambda **kwargs: (EnvironmentCheck("python", "ok", "3.12.4"),),
    )

    assert cli.main(["doctor"]) == 0


class _FakeResult:
    def __init__(self, tmp_path, *, rainfall_status="disabled"):
        from types import SimpleNamespace

        html = tmp_path / "report.html"
        html.parent.mkdir(parents=True, exist_ok=True)
        html.write_text("<html></html>", encoding="utf-8")
        self.source_kind = "extent_csv"
        self.rainfall_status = rainfall_status
        self.rainfall_source = "none"
        self.rainfall_error = None
        self.rainfall_comparison_error = None
        self.warnings = ()
        self.analysis = SimpleNamespace(
            regime=SimpleNamespace(regime="seasonal"),
            route="per_year_detection",
        )
        self.artifacts = SimpleNamespace(
            html=html,
            monthly_csv=tmp_path / "monthly.csv",
            hydro_years_csv=tmp_path / "years.csv",
            wet_event_csv=tmp_path / "events.csv",
            low_spells_csv=tmp_path / "spells.csv",
        )
