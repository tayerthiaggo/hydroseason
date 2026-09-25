"""Build the example reports published with the documentation and README.

Fitzroy is published twice: as a full output bundle (HTML, four CSVs, run
manifest) under ``docs/examples/fitzroy-river-wa/``, and as the standalone
``docs/examples/fitzroy-river-wa.html`` that existing links point to.
Inputs are passed as POSIX paths relative to the repository root so the
published manifest records no machine-specific paths.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hydroseason import run_hydroseason  # noqa: E402

os.chdir(REPO_ROOT)
DOCS_EXAMPLES = Path("docs") / "examples"
DOCS_EXAMPLES.mkdir(parents=True, exist_ok=True)
EXTENT = "case_studies/data/extent"
RAINFALL = "case_studies/data/rainfall"


def _build_bundle(bundle_dir: Path, **workflow_kwargs):
    """Write a complete, fresh output bundle into ``bundle_dir``."""
    if bundle_dir.exists():
        shutil.rmtree(bundle_dir)
    return run_hydroseason(**workflow_kwargs, output_dir=bundle_dir, show_map=True)


def _build_example(*, target_name: str, **workflow_kwargs) -> Path:
    """Build in isolation and copy only the standalone HTML into docs."""
    if Path(target_name).name != target_name:
        raise ValueError("target_name must be a filename, not a path")
    build_dir = DOCS_EXAMPLES / f".build-{Path(target_name).stem}"
    try:
        result = _build_bundle(build_dir, **workflow_kwargs)
        target = DOCS_EXAMPLES / target_name
        shutil.copyfile(result.artifacts.html, target)
    finally:
        shutil.rmtree(build_dir, ignore_errors=True)
    return target


print("Generating Fitzroy River (WA) bundle...")
fitzroy = _build_bundle(
    DOCS_EXAMPLES / "fitzroy-river-wa",
    water_source=f"{EXTENT}/fitzroy_river_wa_30m.csv",
    aoi="data/fitzroy_catchment.geojson",
    aoi_name="Fitzroy River (WA)",
    report_title="Fitzroy River (WA)",
    report_subtitle="Surface Water Dynamics Report",
)
shutil.copyfile(fitzroy.artifacts.html, DOCS_EXAMPLES / "fitzroy-river-wa.html")
print("Fitzroy bundle:", fitzroy.artifacts.html.parent)

print("Generating Fitzroy River (WA) with rainfall...")
fitzroy_rain_html = _build_example(
    target_name="fitzroy-river-wa-rainfall.html",
    water_source=f"{EXTENT}/fitzroy_river_wa_30m.csv",
    aoi="data/fitzroy_catchment.geojson",
    rainfall_csv_path=f"{RAINFALL}/fitzroy_river_wa_silo_rainfall.csv",
    aoi_name="Fitzroy River (WA)",
    report_title="Fitzroy River (WA)",
    report_subtitle="Surface Water & Rainfall Dynamics Report",
)
print("Fitzroy rainfall HTML:", fitzroy_rain_html)

print("Generating Lachlan River (NSW)...")
lachlan_html = _build_example(
    target_name="lachlan-river-nsw.html",
    water_source=f"{EXTENT}/lachlan_river_nsw_30m.csv",
    aoi="data/lachlan_catchment.geojson",
    aoi_name="Lachlan River (NSW)",
    report_title="Lachlan River (NSW)",
    report_subtitle="Surface Water Dynamics Report",
)
print("Lachlan HTML:", lachlan_html)

print("All documentation examples generated successfully!")
