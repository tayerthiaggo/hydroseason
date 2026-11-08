"""Where the dry season ends: the dry run of a trough boundary.

On a flat-bottomed trough many months tie as the minimum, and the boundary
search picks one of them near the expected trough month, often at the start
of the flat run. The dry season, though, ends when water returns. This module
follows the boundary's low run forward and backward, past the search window
and over unobserved months, and reports where it starts, where it ends, the
first month above it (the re-wetting month) and how sure the end is. The
boundary itself does not move.

The run end was tested against known truth before adoption (DE1,
``docs/handoff/2026-11-05-de1-dry-run-end-results.md``): it dates the end of
the dry season better than the boundary on ephemeral seasons and no worse on
smooth ones. A ``point`` end status failed DE1's safety rule, so the end is
reported as ``interval`` (a re-wetting month was observed) or ``censored``
(the record ends dry), never ``point``. Moving the boundary to the run end
(DE1's change B) failed its implementation checks and was withdrawn
(``docs/handoff/2026-11-06-dry-run-end-implementation.md``).

A month is observed when ``quality_state == "usable"``. A run continues while
observed months stay within the boundary's own tolerance
(``_epsilon_pp`` at the boundary month) of the boundary's extent; unobserved
months neither extend nor end it. A mid-dry rain pulse above the tolerance
ends the run, as a zero-flow period ends when flow resumes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd

from ._boundary import _epsilon_pp

DRY_RUN_RULE = "report_dry_run"
DRY_RUN_RULE_VERSION = 1
# DE2 candidate rules (not adopted unless DE2 passes).
ANCHOR_RULE = "end_of_climatological_low"
ANCHOR_RULE_VERSION = 1
ANCHOR_RANGE_FRACTION = 0.1
ZERO_LOW_LABEL_RULE = "zero_low_end_status"
ZERO_LOW_LABEL_RULE_VERSION = 2

DryEndStatus = Literal["interval", "censored", "unavailable"]


@dataclass(frozen=True)
class DryRun:
    """The low run of one trough boundary."""

    start: pd.Timestamp | None
    end: pd.Timestamp | None
    rewetting: pd.Timestamp | None
    end_status: DryEndStatus
    level_pct: float | None
    tolerance_pp: float | None

    @property
    def months(self) -> int | None:
        if self.start is None or self.end is None:
            return None
        return (self.end.year - self.start.year) * 12 + self.end.month - self.start.month + 1

    @classmethod
    def unavailable(cls) -> "DryRun":
        return cls(None, None, None, "unavailable", None, None)


def find_dry_run(
    frame: pd.DataFrame,
    boundary: pd.Timestamp | None,
    *,
    noise_pp: float,
    amplitude_pp: float,
    previous_peak: pd.Timestamp | None = None,
    next_peak: pd.Timestamp | None = None,
) -> DryRun:
    """Follow the low run of ``boundary`` in a prepared monthly frame.

    A reported peak month that is not observed (too cloudy to be ``usable``)
    still ends the run: the run cannot pass the peak of the next cycle
    (``next_peak``, which then counts as the re-wetting month) or start before
    the peak of its own cycle (``previous_peak``). An observed peak is judged
    like any other month.
    """
    if boundary is None or pd.isna(boundary):
        return DryRun.unavailable()
    boundary = pd.Timestamp(boundary)
    if boundary not in frame.index or pd.isna(frame.at[boundary, "extent_pct"]):
        return DryRun.unavailable()

    level = float(frame.at[boundary, "extent_pct"])
    tolerance = float(_epsilon_pp(frame.loc[boundary], noise_pp=noise_pp, amplitude_pp=amplitude_pp))
    observed = (frame["quality_state"] == "usable").to_numpy()
    values = frame["extent_pct"].to_numpy(float)
    months = list(frame.index)
    position = months.index(boundary)

    end, rewetting = position, None
    for i in range(position + 1, len(months)):
        if not observed[i] and next_peak is not None and months[i] == next_peak:
            rewetting = i
            break
        if not observed[i]:
            continue
        if values[i] <= level + tolerance:
            end = i
        else:
            rewetting = i
            break

    start = position
    for i in range(position - 1, -1, -1):
        if not observed[i] and previous_peak is not None and months[i] == previous_peak:
            break
        if not observed[i]:
            continue
        if values[i] <= level + tolerance:
            start = i
        else:
            break

    return DryRun(
        start=pd.Timestamp(months[start]),
        end=pd.Timestamp(months[end]),
        rewetting=None if rewetting is None else pd.Timestamp(months[rewetting]),
        end_status="censored" if rewetting is None else "interval",
        level_pct=level,
        tolerance_pp=tolerance,
    )
