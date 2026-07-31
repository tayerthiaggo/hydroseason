import tomllib
from pathlib import Path

from scripts.check_release_metadata import validate_release_metadata


def test_first_remote_sensing_release_version_is_0_1_0():
    root = Path.cwd()
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["version"] == "0.1.0"
    assert 'version: "0.1.0"' in (root / "CITATION.cff").read_text(encoding="utf-8")


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
