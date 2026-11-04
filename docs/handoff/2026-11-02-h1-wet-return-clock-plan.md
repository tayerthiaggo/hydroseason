# H1: where to read the wet-return clock (draft pre-registration)

Status: **parked in the library; offered to hydropools.** The project lead decided on 2026-11-02 that HydroSeason is not referenced to gauges: extent and discharge measure different things. This draft is kept as a starting point if hydropools wants to test its own clock against its gauge referee. Nothing below has been run.

Background: decision H1 in [2026-11-02-decisions-units-dates-hydropools.md](2026-11-02-decisions-units-dates-hydropools.md). An exploratory re-scoring of the hydropools referee found two things:
- The month after the trough (the next hydrological year's `start_date`) matches gauge first flow better than the trough itself.
- A catchment-wide value matches tributaries better than a local one.

Both findings come from Fitzroy and Gilbert gauges that had already been looked at. This test uses gauges that have not been.

## Question

For "the month the wet season returns", is the next hydrological year's `start_date` read at a large unit (the basin, or its level-7 subbasins where the basin is aseasonal) closer to gauge first flow than the same date read locally?

## Gauges

- **Eligible stations:** every Bureau of Meteorology Water Data Online station with a daily discharge series (`DMQaQc.Merged.DailyMean.24HR`) whose location lies inside one of the five study areas of the spatial unit study:
  - Daly;
  - Fitzroy WA (the BoM ∩ DWER outline);
  - Gilbert;
  - Lachlan;
  - Moonie.
- **Excluded:** the 15 gauges hydropools already scored: 802002, 802003, 802004, 802005, 802006, 802007, 802008, 802055, 802137, 802156, 802198, 802202, 802203, 802213 and 917001D.
- **Intermittent:** discharge at or below 0.01 m³/s on at least 5% of days with data between 2005-01-01 and 2025-12-31.
- **Enough years:** at least 5 scorable frames (below).
- **Series choice:** when a station has more than one discharge series under that name, the one with the longest coverage is used.

The inventory of eligible gauges is fixed by these rules before any clock is read.

## Referee

- **Frame:** 12 months starting at the gauge's peak-flow month, which is the calendar month with the highest median daily discharge over 2005–2025. This keeps the dry season inside one frame both in the monsoonal north and in the winter-rainfall upper Lachlan.
- **Scorable frame:** at least 80% of days have data, and the frame holds a zero-flow spell of at least 14 consecutive days at or below 0.01 m³/s.
- **Gauge end-dry month `g`:** the month of the last day of the longest such spell in the frame.
- **Other frames:** frames without a qualifying spell are counted as flow-through and reported, but not scored.

## Clocks

Every clock comes from the series built in the spatial unit study. The series is analysed exactly as there, `analyze_catchment(extent, phase_scheme="two_phase", quality_policy="flag")`, at the commit recorded in the receipt, and the hydrological-years table is kept.

| Clock | Unit | Date |
| --- | --- | --- |
| **B** | The basin (catchment unit); where the basin routes aseasonal, the level-7 subbasin containing the gauge (decision H2) | `start_date` |
| **S7** | The HydroBASINS level-7 subbasin containing the gauge | `start_date` |
| **L** | The HydroBASINS level-8 subbasin containing the gauge (the local unit) | `start_date` |
| **T0** | Same unit as L | `trough_boundary_date` (current practice) |

The clock month for a frame is the clock's date that falls inside the frame. If there are several, the first is used. If there is none, the frame has no clock for that candidate.

## Outcomes

Each candidate gets three numbers. Uncertainty comes from 2,000 bootstrap draws (seed 0) that resample gauges with their frames; 95% percentile intervals.
- **Hit rate:** share of scorable frames with a clock where |clock − g| ≤ 1 month.
- **Late share:** share where clock − g > 1 month.
- **Coverage:** share of scorable frames with a clock.

## Decision rules

**Primary: B against L.**
- **Large unit better:** hit(B) − hit(L) ≥ 0.05 with interval lower bound > 0, late(B) ≤ 0.10, and coverage(B) ≥ coverage(L) − 0.05.
- **Local better:** the mirror rule.
- **Equivalent:** the hit-rate difference has its interval inside ±0.05.
- **Inconclusive:** anything else.

**Secondary:**
- **The +1 rule:** does L beat T0, by the same rule?
- **Subbasin level:** S7 against L.
- **Basin against subbasin:** B against S7, in the catchments whose basin routes seasonal.
- **Per catchment:** results reported for each catchment.

**Sensitivity:** the primary comparison without the Fitzroy gauges, because the Fitzroy basin clock was used in the exploratory re-scoring.

## What each result means for hydropools

| Result | Action |
| --- | --- |
| Large unit better | Adopt H1 and H2: read the clock at the basin, fall back to level-7 subbasins, then retire the reach-level merge chain (H3). |
| Equivalent | Adopt the basin clock for its lower cost; say the evidence does not separate them. |
| Local better | Keep reach-level clocks; do not adopt H1. |
| Inconclusive | No change; report the gauge-years needed for a decisive test. |
| L does not beat T0 | Do not shift the clock by one month. |

## Limits stated in advance

- **Local unit:** level-8 subbasins (about 480 km²) stand in for hydropools reaches, which are smaller.
- **Data:** five catchments; gauges were not chosen for representativeness.
- **Upper Lachlan:** a winter-rainfall system, different from the monsoonal north.
- **Referee:** the end of the longest zero-flow spell is one definition of first flow. On flashy streams a lull inside the wet season can still produce a long spell.
