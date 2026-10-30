import csv

from scripts.trough_falsification_sweep import COLUMNS, main


def test_sweep_writes_one_row_per_seed_and_a_summary(tmp_path):
    out = tmp_path / "matrix.csv"
    summary = tmp_path / "summary.md"

    code = main(
        [
            "--seeds", "2",
            "--constructions", "stable", "drift",
            "--years", "7",
            "--floods", "0.3",
            "--gaps", "none",
            "--out", str(out),
            "--summary", str(summary),
        ]
    )

    assert code == 0
    with out.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 4
    assert list(rows[0].keys()) == COLUMNS
    assert {row["construction"] for row in rows} == {"stable", "drift"}
    assert {row["seed"] for row in rows} == {"0", "1"}
    text = summary.read_text(encoding="utf-8")
    assert "| stable/7/0.3/none/False |" in text
    assert "| drift/7/0.3/none/False |" in text
