import csv

from scripts.frozen_window_recurrence import circular_distance, decide, main
from scripts.trough_synthetic import build_record


def _write_fixture(directory, name, kind, seed):
    _, frame = build_record(kind, seed=seed)
    frame.rename_axis("date").reset_index().to_csv(directory / f"{name}.csv", index=False)


def test_circular_distance_wraps_december_to_january():
    assert circular_distance(12, 1) == 1
    assert circular_distance(3, 9) == 6
    assert circular_distance(7, 7) == 0


def test_decide_outcomes():
    ok = {"status": "ok"}
    recurs = {**ok, "trough_recurs": True, "compact_and_agrees": True}
    recurs_wide = {**ok, "trough_recurs": True, "compact_and_agrees": False}
    silent = {**ok, "trough_recurs": False, "compact_and_agrees": False}
    short = {"status": "insufficient_record", "trough_recurs": False, "compact_and_agrees": False}

    assert decide([recurs, recurs, recurs])["outcome"] == "A"
    assert decide([silent, silent, silent])["outcome"] == "B"
    assert decide([recurs_wide, recurs_wide, silent])["outcome"] == "inconclusive"
    assert decide([short])["outcome"] == "inconclusive"
    assert decide([recurs, recurs, short])["n_ok"] == 2


def test_runner_reports_outcome_a_for_recurrent_troughs(tmp_path):
    fixtures = tmp_path / "windows"
    fixtures.mkdir()
    for seed in range(3):
        _write_fixture(fixtures, f"stable_{seed}", "stable", seed)
    ranks = tmp_path / "ranks.csv"
    ranks.write_text(
        "window_id,rank_trough_month\nstable_0,9\nstable_1,10\nstable_2,8\n", encoding="utf-8"
    )
    out = tmp_path / "windows.csv"
    summary = tmp_path / "windows.md"

    code = main(
        [
            "--fixtures", str(fixtures),
            "--out", str(out),
            "--summary", str(summary),
            "--rank-troughs", str(ranks),
        ]
    )

    assert code == 0
    with out.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["window_id"] for row in rows] == ["stable_0", "stable_1", "stable_2"]
    assert all(row["regime"] == "aseasonal" for row in rows)
    assert all(row["trough_recurs"] == "True" for row in rows)
    assert all(row["trough_dominant_month"] == "9" for row in rows)
    assert all(int(row["circular_distance_to_rank"]) <= 1 for row in rows)
    assert summary.read_text(encoding="utf-8").startswith("Outcome: **A**")


def test_runner_reports_outcome_b_for_drifting_troughs(tmp_path):
    fixtures = tmp_path / "windows"
    fixtures.mkdir()
    for seed in range(3):
        _write_fixture(fixtures, f"drift_{seed}", "drift", seed)
    out = tmp_path / "windows.csv"
    summary = tmp_path / "windows.md"

    code = main(["--fixtures", str(fixtures), "--out", str(out), "--summary", str(summary)])

    assert code == 0
    assert summary.read_text(encoding="utf-8").startswith("Outcome: **B**")
