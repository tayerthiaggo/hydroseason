# Manager Report Chart Revamp Design

## Goal

Revamp the offline manager HTML report so the primary monthly water-extent
chart is full width, visually informative, and interactive. Add a separate
full-width hydrological-year extent chart below it. Keep the report offline,
Plotly-powered, CSV-compatible, and suitable for later visual refinements.

## User decisions

- Monthly Surface Water Extent is the most important chart and spans the page.
- Supporting View moves below the two primary charts and is unchanged in this pass.
- Linear scale is the default; users can switch to log scale.
- Monthly phase context uses `recovery`, `wet`, `recession`, and `dry`.
- Monthly chart includes reference median and invalid percentage on a secondary axis.
- Peak, mid-dry, and end-dry markers come from hydrological-year exports.
- HY chart uses the same chronological x-axis and synchronized navigation.
- HY intervals run from month-after-end-dry through end-dry and display `HY ####` labels.

## Layout

The report order becomes:

1. Header, quality note, verdict, and KPI cards.
2. Full-width `Monthly Surface Water Extent` card with scale controls.
3. Full-width `Hydrological Year Extent` card.
4. Supporting View card, moved lower for future editing.
5. Existing hydrological-year, event, low-spell, and method tables.

The two primary chart containers remain separate DOM elements so each can have
its own styling and content while JavaScript synchronizes their x-axis range.

## Monthly chart

The chart keeps the chronological monthly extent line as the main trace. It
also renders:

- dashed reference median trace when available;
- invalid percentage as an amber line on a linear right-hand y-axis;
- low-opacity phase bands for recovery, wet, recession, and dry;
- peak, mid-dry, and end-dry markers sourced from HY-derived monthly flags;
- hover fields for date, extent, reference median, invalid percentage, phase,
  HY year, and marker status.

The left y-axis defaults to linear. The `Linear scale` and `Log scale` controls
change the left axis type without changing the invalid-percentage axis. Log
mode clamps non-positive extent values to a small display floor while retaining
the original values in hover data.

Plotly remains responsible for drag zoom, mouse-wheel zoom, pan, reset, image
export, and responsive resizing. A range slider provides quick navigation over
the full date range.

## Hydrological-year chart

The lower chart repeats the extent series on the same date domain. Detected HY
intervals are represented by low-opacity bands spanning month-after-end-dry to
end-dry, with centered `HY ####` labels. Peak, mid-dry, and end-dry markers are
shown using the same marker vocabulary as the monthly chart. Partial or
missing intervals are omitted safely; the chart still renders the extent line.

Both charts synchronize x-axis range changes in both directions for zoom, pan,
reset, and range-slider interaction. Y-axis scale changes are local to the
monthly chart.

## Code boundaries

- `_report_plotly.py`: add phase styling/constants, enrich
  `timeline_figure`, and add `hydro_year_figure`.
- `_report_html.py`: carry the new figure in the serialized payload, render
  the chart controls/containers, and add narrowly scoped synchronization JS.
- Public report APIs and CSV export schemas remain unchanged.
- No changes to the deferred Supporting View design.

## Failure and compatibility behavior

- All JSON payloads must continue to serialize with `allow_nan=False`.
- Missing phase, HY, reference-median, or invalid-percentage data must not
  prevent report generation.
- The report remains fully self-contained with the pinned vendored Plotly
  runtime and no CDN/script tags.
- Existing legacy compatibility reports continue to render; they receive the
  same shell safely, without requiring the new HY data.

## Verification

Add tests before implementation for:

- phase bands and marker traces in the monthly figure;
- reference median and invalid percentage secondary-axis traces;
- linear default and log-compatible axis configuration;
- HY interval labels/bands and boundary markers;
- HTML controls, chart containers, synchronization hooks, and offline shell;
- unchanged CSV filenames/schema and existing report behavior.

After implementation, run focused report/plotly tests, the full test suite, and
regenerate the Fitzroy report for manual browser inspection.
