"""Build standalone HTML examples for documentation and README."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hydroseason import run_hydroseason  # noqa: E402

DOCS_EXAMPLES = REPO_ROOT / "docs" / "examples"
DOCS_EXAMPLES.mkdir(parents=True, exist_ok=True)

def _build_example(*, target_name: str, **workflow_kwargs) -> Path:
    """Build in isolation and copy only the standalone HTML into docs."""
    if Path(target_name).name != target_name:
        raise ValueError("target_name must be a filename, not a path")
    build_dir = DOCS_EXAMPLES / f".build-{Path(target_name).stem}"
    if build_dir.exists():
        shutil.rmtree(build_dir)
    build_dir.mkdir()
    try:
        result = run_hydroseason(
            **workflow_kwargs,
            output_dir=build_dir,
            show_map=True,
        )
        target = DOCS_EXAMPLES / target_name
        shutil.copyfile(result.artifacts.html, target)
    finally:
        shutil.rmtree(build_dir)
    return target


print("Generating Fitzroy River (WA)...")
fitzroy_html = _build_example(
    target_name="fitzroy-river-wa.html",
    water_source=(
        REPO_ROOT / "case_studies" / "data" / "extent" / "fitzroy_river_wa_30m.csv"
    ),
    aoi=REPO_ROOT / "data" / "catchments" / "fitzroy_river_wa_boundary.geojson",
    aoi_name="Fitzroy River (WA)",
    report_title="Fitzroy River (WA)",
    report_subtitle="Surface Water Dynamics Report",
)
print("Fitzroy HTML:", fitzroy_html)

print("Generating Fitzroy River (WA) with rainfall...")
fitzroy_rain_html = _build_example(
    target_name="fitzroy-river-wa-rainfall.html",
    water_source=(
        REPO_ROOT / "case_studies" / "data" / "extent" / "fitzroy_river_wa_30m.csv"
    ),
    aoi=REPO_ROOT / "data" / "catchments" / "fitzroy_river_wa_boundary.geojson",
    rainfall_csv_path=(
        REPO_ROOT
        / "case_studies"
        / "data"
        / "rainfall"
        / "fitzroy_river_wa_silo_rainfall.csv"
    ),
    aoi_name="Fitzroy River (WA)",
    report_title="Fitzroy River (WA)",
    report_subtitle="Surface Water & Rainfall Dynamics Report",
)
print("Fitzroy rainfall HTML:", fitzroy_rain_html)

print("Generating Lachlan River (NSW)...")
lachlan_html = _build_example(
    target_name="lachlan-river-nsw.html",
    water_source=(
        REPO_ROOT / "case_studies" / "data" / "extent" / "lachlan_river_nsw_30m.csv"
    ),
    aoi=REPO_ROOT / "data" / "catchments" / "lachlan_river_nsw_boundary.geojson",
    aoi_name="Lachlan River (NSW)",
    report_title="Lachlan River (NSW)",
    report_subtitle="Surface Water Dynamics Report",
)
print("Lachlan HTML:", lachlan_html)

print("All documentation examples generated successfully!")
