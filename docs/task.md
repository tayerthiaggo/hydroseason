# Implementation Tasks

## P0 — True Liebmann Fix (`dynamic_season.py`)
- [x] Replace block-picker in `segment_by_cumulative_anomaly` with true argmin/argmax cumsum logic
- [x] Add `smooth_anomalies` param (3-month rolling before cumsum)
- [x] Add `abs_floor` param (months < floor never Wet, pre-gate before anomaly calc)
- [x] Add `min_net_gain` guard (cumsum rise must exceed threshold to label any Wet)

## P0 — Config update (`config.py`)
- [x] Add `cumulative_anomaly_absolute_floor` field (default 10.0)
- [x] Add `cumulative_anomaly_smooth` bool (default True)
- [x] Add `segmentation_method` allow `"hybrid"` as new option

## P1 — Two-Stage Hybrid (`pipeline.py`)
- [x] Implement `"hybrid"` branch: run true Liebmann first → get [onset, demise] window per year → run heuristic only inside that window
- [x] Add clipping logic: mask months outside Liebmann window as Dry before heuristic runs

## P2 — Climatology & Multi-year Improvements
- [x] Implement STL residual gate on anomaly computation (outlier capping)
- [x] Implement multi-year continuous cumulative sum option

## Verify
- [x] Run unit tests and integration tests (all 209 tests passed)
- [x] Check lonely months eliminated via unit tests
