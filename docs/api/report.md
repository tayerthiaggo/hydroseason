# Reporting

Self-contained HTML report and matching CSV bundle export. Column
dictionary: [Report Export Columns](../report-columns.md).

## AOI boundary maps

When `generate_catchment_report` receives `aoi_context`, the self-contained
HTML embeds a compact Leaflet runtime and boundary GeoJSON. The boundary
remains readable without tiles. The basemap is deliberately not embedded:
viewing the report requests standard OpenStreetMap tiles and therefore needs
an internet connection; a tile failure only exposes the offline notice and
does not affect report content. `aoi_context` geometry may be simplified for
display and must not be treated as the analysed footprint.

`generate_catchment_report(..., aoi_context=None)` preserves existing
map-free reports. `CatchmentReportPaths` remains the five generated paths:
HTML plus monthly, hydrological-year, wet-event, and low-spell CSV files.
Reports display public results derived under `established_0_1_1`. Any displayed
harmonic or recoverability details belong to the experimental challenger, which
does not control public decisions or outputs.

::: hydroseason.report
    options:
      members:
        - generate_catchment_report
        - generate_html_report
        - CatchmentReportPaths
      show_root_heading: true
      show_source: false
      heading_level: 2
