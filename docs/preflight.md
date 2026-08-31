# Preflight: what the record can support

Preflight asks whether an AOI's satellite record can carry the analysis at
all — before any monthly acquisition is paid for. Two questions live here,
deliberately kept apart because they have different answer shapes and
different maturity.

## Is there any recurrent surface water?

`run_hydroseason` applies this screen automatically on every regular DEA
run. One all-time WOfS Statistics read decides it, using fixed constants:
pixels wet at or above 10% recurrence must form a contiguous cluster of at
least the minimum pixel count for the run's resolution.

Nothing is configurable here, and nothing needs to be. If the AOI passes, the
same Statistics read is handed straight to monthly acquisition as the
`count_wet > 0 AND AOI` maximum-water mask — so the screen costs no extra
query. If it fails, the run stops:

```python
from hydroseason import run_hydroseason, HydroSeasonPreflightError

try:
    result = run_hydroseason(
        None,
        aoi="catchment.geojson",
        start_date="2005-01-01",
        end_date="2025-12-01",
        output_dir="output/report",
    )
except HydroSeasonPreflightError as exc:
    print(exc.result.reason)
    print(exc.result.core_pixel_count, exc.result.largest_cluster_pixels)
```

`HydroSeasonPreflightError.result` is a `FeasibilityResult` carrying the
measured quantities behind the rejection, so the decision can be audited
rather than taken on trust. On a successful run the same object is available
as `result.preflight_result`.

!!! note "An outage is not an answer"
    If DEA Statistics cannot be reached, `run_hydroseason` warns and
    continues into monthly acquisition. Converting a service outage into a
    "no water here" result would be scientifically wrong, so it never
    happens.

Run the same screen on its own, without committing to an analysis:

```python
from hydroseason import preflight

feasibility = preflight(
    "catchment.geojson", "2005-01-01", "2025-12-01",
    feasibility_only=True,
)
print(feasibility.feasible, feasibility.reason)
```

Called standalone this path re-raises a Statistics outage instead of warning:
you asked the question directly, so you get the failure directly.

## Is the record dense enough for per-year detection?

The second question is broader, and its answer is a `PreflightResult`
carrying three independent decisions — each `"pass"`, `"fail"`,
`"indeterminate"`, or `"not_assessed"`:

| Decision | Question |
|---|---|
| `candidate_decision` | Does the Statistics grid hold enough reliably-observed, recurrently-wet pixels for this AOI to be a candidate at all? |
| `monthly_decision` | Is the monthly record dense enough — usable months, months per year, supported years — for per-year detection? |
| `timing_decision` | Is calendar-month coverage even enough to trust seasonal timing? |

The monthly and timing decisions need a monthly record. Without one they
report `"not_assessed"`, which means the question was not answered — not that
it was answered negatively.

```python
result = preflight(
    "catchment.geojson", "2005-01-01", "2025-12-01",
    monthly_observations="cache/catchment.zarr",
    thresholds="diagnostic",
)
print(result.summary())
print(result.reasons)
payload = result.to_dict()
```

### Thresholds are not calibrated yet

!!! warning "`thresholds="default"` raises"
    The reviewed threshold profile has **not** been installed in 0.2.0.
    Calling `preflight(...)` without a `thresholds` argument raises
    `PreflightProfileUnavailable` rather than guessing at cut-offs that were
    never reviewed.

Two modes work today:

- **`thresholds="diagnostic"`** measures every metric with all cut-offs at
  zero. Nothing is gated, so the decisions carry no scientific authority —
  what you get is the measurement, to inspect on its own terms.
- **A `PreflightThresholds` instance** applies cut-offs you declare, under a
  `profile_name` and `profile_version` you choose, so results stay
  attributable to the profile that produced them.

`feasibility_only=True` ignores `thresholds` entirely and is unaffected by
any of this.

### Cost

Outside `feasibility_only`, preflight reads annual Statistics rather than the
all-time grid, so it is the more expensive of the two questions.
`wet_aoi_require_year_union` defaults to `False` here — the opposite of
monthly acquisition, which keeps that per-year mask-union safety net. On a
large catchment the union accounts for roughly 92% of preflight runtime, and
a preflight decision is a routing call, not a forensic record.

## What each result carries

- `FeasibilityResult` — `feasible`, `reason`, and the measured
  `core_pixel_count`, `cluster_count`, `largest_cluster_pixels`,
  `minimum_cluster_pixels`. `to_dict()` returns a JSON-ready payload.
- `PreflightResult` — the three decisions and their reason codes,
  `candidate_metrics`/`monthly_metrics`, the `thresholds` profile that was
  applied, `capabilities`, `warnings`, and `provenance` recording the
  Statistics request and monthly source identity. `summary()` renders one
  line; `to_dict()` returns a JSON-ready payload (`flat=False` for the nested
  form).

Full signatures: [API Reference — Preflight](api/preflight.md).
