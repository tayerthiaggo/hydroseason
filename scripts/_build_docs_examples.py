"""Build standalone HTML examples for documentation and README."""
from pathlib import Path
import shutil

from hydroseason import run_hydroseason

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_EXAMPLES = REPO_ROOT / "docs" / "examples"
DOCS_EXAMPLES.mkdir(parents=True, exist_ok=True)

# 1. Fitzroy River (WA)
print("Generating Fitzroy River (WA)...")
res_fitzroy = run_hydroseason(
    water_source=REPO_ROOT / "case_studies" / "data" / "extent" / "fitzroy_river_wa_30m.csv",
    aoi=REPO_ROOT / "data" / "catchments" / "fitzroy_river_wa_boundary.geojson",
    aoi_name="Fitzroy River (WA)",
    report_title="Fitzroy River (WA)",
    report_subtitle="Surface Water Dynamics Report",
    output_dir=DOCS_EXAMPLES,
    show_map=True,
)
print("Fitzroy HTML:", res_fitzroy.artifacts.html)
if res_fitzroy.artifacts.html.name != "fitzroy-river-wa.html":
    shutil.copyfile(res_fitzroy.artifacts.html, DOCS_EXAMPLES / "fitzroy-river-wa.html")

# 2. Fitzroy River (WA) with rainfall context
print("Generating Fitzroy River (WA) with rainfall...")
res_fitzroy_rain = run_hydroseason(
    water_source=REPO_ROOT / "case_studies" / "data" / "extent" / "fitzroy_river_wa_30m.csv",
    aoi=REPO_ROOT / "data" / "catchments" / "fitzroy_river_wa_boundary.geojson",
    rainfall_csv_path=REPO_ROOT / "case_studies" / "data" / "rainfall" / "fitzroy_river_wa_silo_rainfall.csv",
    aoi_name="Fitzroy River (WA)",
    report_title="Fitzroy River (WA)",
    report_subtitle="Surface Water & Rainfall Dynamics Report",
    output_dir=DOCS_EXAMPLES,
    show_map=True,
)
print("Fitzroy rainfall HTML:", res_fitzroy_rain.artifacts.html)
shutil.copyfile(res_fitzroy_rain.artifacts.html, DOCS_EXAMPLES / "fitzroy-river-wa-rainfall.html")

# 3. Lachlan River (NSW)
print("Generating Lachlan River (NSW)...")
res_lachlan = run_hydroseason(
    water_source=REPO_ROOT / "case_studies" / "data" / "extent" / "lachlan_river_nsw_30m.csv",
    aoi=REPO_ROOT / "data" / "catchments" / "lachlan_river_nsw_boundary.geojson",
    aoi_name="Lachlan River (NSW)",
    report_title="Lachlan River (NSW)",
    report_subtitle="Surface Water Dynamics Report",
    output_dir=DOCS_EXAMPLES,
    show_map=True,
)
print("Lachlan HTML:", res_lachlan.artifacts.html)
if res_lachlan.artifacts.html.name != "lachlan-river-nsw.html":
    shutil.copyfile(res_lachlan.artifacts.html, DOCS_EXAMPLES / "lachlan-river-nsw.html")

print("All documentation examples generated successfully!")
