"""Run DE2's frozen evaluate stage with one post-freeze fix (a deviation, reported).

The frozen script seeds the reported noise-band breakdown with 400 + the band's lower
bound, and the first band starts at k = 0.5, so numpy received a non-integer seed and
the stage stopped before writing results. This wrapper leaves scripts/known_truth_de2.py
byte-identical and turns a non-integer seed s into round(10 s). Only the reported
noise-band breakdown uses such a seed; every decision rule's seed is an integer and is
passed through unchanged.

    PYTHONPATH=. python scripts/known_truth_de2_evaluate.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import known_truth_de2 as de2  # noqa: E402

_frozen_bootstrap = de2.bootstrap_difference


def _integer_seed(table, seed):
    return _frozen_bootstrap(table, int(seed) if float(seed).is_integer() else int(round(10 * seed)))


de2.bootstrap_difference = _integer_seed

if __name__ == "__main__":
    de2.stage_evaluate()
