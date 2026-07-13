import importlib
import tomllib
from pathlib import Path


def test_package_import_exposes_only_migration_safe_surface():
    hydroseason = importlib.import_module("hydroseason")

    assert isinstance(hydroseason.__version__, str)
    assert hydroseason.__all__ == [
        "__version__",
        "HydroYearConfig",
        "detect_hydrological_years",
        "label_hydrological_months",
        "monthly_water_extent",
        "load_aoi",
        "load_wofs_from_stac",
        "load_monthly_masks",
        "load_monthly_masks_zarr",
        "load_extent_csv",
        "complete_monthly_axis",
    ]
    assert callable(hydroseason.detect_hydrological_years)
    assert callable(hydroseason.label_hydrological_months)
    assert callable(hydroseason.load_extent_csv)
    assert "ValidationSeasonConfig" not in vars(hydroseason)

    stripped_names = {
        "classify_rainfall",
        "run_pipeline",
        "read_rainfall",
        "get_monthly_silo_rainfall",
        "generate_html_report",
    }
    assert stripped_names.isdisjoint(vars(hydroseason))


def test_package_metadata_has_no_removed_cli_entry_point():
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert "scripts" not in pyproject["project"]
    assert "rainfall" not in pyproject["project"]["description"].lower()


def test_conda_recipe_has_no_removed_cli_entry_point():
    recipe = Path("conda/meta.yaml").read_text(encoding="utf-8")

    assert "hydroseason.cli:main" not in recipe
    assert "hydroseason --version" not in recipe
