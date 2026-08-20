from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]

from scripts.check_release_metadata import validate_release_metadata


def test_raster_extra_keeps_zarr_2_compatible_with_numcodecs():
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert "numcodecs<0.16" in project["project"]["optional-dependencies"]["raster"]


def test_build_smokes_read_the_expected_version_from_project_metadata():
    workflow = Path(".github/workflows/test.yml").read_text(encoding="utf-8")

    expected_assertion = (
        "assert hydroseason.__version__ == "
        "'${{ steps.project-version.outputs.version }}'"
    )
    assert "id: project-version" in workflow
    assert workflow.count(expected_assertion) == 2
    assert "assert hydroseason.__version__ == '0.1.0'" not in workflow


def test_repository_metadata_is_consistent_before_release():
    assert validate_release_metadata(
        Path.cwd(), expected_tag=None, require_released=False
    ) == []


def test_release_mode_requires_version_heading_and_release_date(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="hydroseason"\nversion="0.1.0"\n', encoding="utf-8"
    )
    (tmp_path / "CITATION.cff").write_text(
        'version: "0.1.0"\n', encoding="utf-8"
    )
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
    (tmp_path / "hydroseason").mkdir()
    (tmp_path / "hydroseason" / "__init__.py").write_text(
        '__version__ = "0.1.0"\n', encoding="utf-8"
    )
    errors = validate_release_metadata(
        tmp_path, expected_tag="v0.1.0", require_released=True
    )
    assert any("date-released" in error for error in errors)
    assert any("CHANGELOG" in error for error in errors)


def test_release_mode_rejects_mismatched_release_dates(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="hydroseason"\nversion="0.1.0"\n', encoding="utf-8"
    )
    (tmp_path / "CITATION.cff").write_text(
        'version: "0.1.0"\ndate-released: "2026-08-06"\n', encoding="utf-8"
    )
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n## [0.1.0] - 2026-08-10\n", encoding="utf-8"
    )
    (tmp_path / "hydroseason").mkdir()
    (tmp_path / "hydroseason" / "__init__.py").write_text(
        '__version__ = "0.1.0"\n', encoding="utf-8"
    )
    errors = validate_release_metadata(
        tmp_path, expected_tag="v0.1.0", require_released=True
    )
    assert "CITATION.cff date-released differs from CHANGELOG release date" in errors


def test_requires_python_matches_the_tested_interpreters():
    """An uncapped requires-python let pip install into Python 3.14, where
    the netCDF4/NumPy native ABI mismatch is a live crash risk and where CI
    has never run. The declared window and the CI matrices must agree."""
    try:
        import tomllib
    except ModuleNotFoundError:  # Python 3.10
        import tomli as tomllib

    from pathlib import Path

    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    classifiers = pyproject["project"]["classifiers"]

    assert pyproject["project"]["requires-python"] == ">=3.10,<3.14"
    for minor in (10, 11, 12, 13):
        assert f"Programming Language :: Python :: 3.{minor}" in classifiers
    assert "Programming Language :: Python :: 3.14" not in classifiers

    workflow = Path(".github/workflows/test.yml").read_text(encoding="utf-8")
    assert workflow.count('python-version: ["3.10", "3.11", "3.12", "3.13"]') == 2
