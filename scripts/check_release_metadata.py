from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]


FORBIDDEN_TRACKED_PREFIXES = (
    "docs/paper/",
    "docs/audits/",
    "docs/superpowers/",
    "case_studies/results/",
    "case_studies/timing-identifiability/",
    "case_studies/trough-refinement/",
    "case_studies/recurrence-identifiability/",
)

FORBIDDEN_CAMPAIGN_SCRIPTS = (
    "scripts/audit_recurrence_impact.py",
    "scripts/build_final_review.py",
    "scripts/build_real_extent_fixture.py",
    "scripts/build_recurrence_identifiability_cohort.py",
    "scripts/build_timing_identifiability_cohort.py",
    "scripts/build_trough_refinement_cohort.py",
    "scripts/check_motivating_records.py",
    "scripts/compare_catchment_resolution_windows.py",
    "scripts/compare_resolution_signal_fidelity.py",
    "scripts/compare_wofs_resampling.py",
    "scripts/evaluate_final_pipeline.py",
    "scripts/evaluate_recurrence_identifiability_cohort.py",
    "scripts/evaluate_timing_identifiability_cohort.py",
    "scripts/evaluate_timing_recurrence.py",
    "scripts/evaluate_trough_refinement_cohort.py",
)


def validate_release_metadata(
    root: Path, *, expected_tag: str | None = None, require_released: bool = False
) -> list[str]:
    root = Path(root)
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]
    version = str(project["version"])
    cff = (root / "CITATION.cff").read_text(encoding="utf-8")
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    init = (root / "hydroseason" / "__init__.py").read_text(encoding="utf-8")
    errors = []
    if f'version: "{version}"' not in cff:
        errors.append("CITATION.cff version differs from pyproject.toml")
    if f'__version__ = "{version}"' not in init:
        errors.append("hydroseason.__version__ fallback differs from pyproject.toml")
    if expected_tag is not None and expected_tag != f"v{version}":
        errors.append(f"tag {expected_tag} does not match version {version}")

    # Scope enforcement via git (only when .git directory exists; skip in unpacked sdist)
    if (root / ".git").is_dir() and shutil.which("git"):
        try:
            res = subprocess.run(
                ["git", "ls-files"],
                capture_output=True,
                text=True,
                check=True,
                cwd=root,
            )
            tracked_files = [
                line.strip().replace("\\", "/")
                for line in res.stdout.splitlines()
                if line.strip()
            ]
            forbidden_found = [
                f
                for f in tracked_files
                if any(f.startswith(prefix) for prefix in FORBIDDEN_TRACKED_PREFIXES)
                or f in FORBIDDEN_CAMPAIGN_SCRIPTS
            ]
            if forbidden_found:
                errors.append(f"Forbidden tracked files found in git: {forbidden_found}")

            res_ignored = subprocess.run(
                ["git", "ls-files", "-c", "-i", "--exclude-standard"],
                capture_output=True,
                text=True,
                check=True,
                cwd=root,
            )
            tracked_ignored = [
                line.strip().replace("\\", "/")
                for line in res_ignored.stdout.splitlines()
                if line.strip()
            ]
            if tracked_ignored:
                errors.append(f"Tracked gitignored files found: {tracked_ignored}")
        except subprocess.SubprocessError as exc:
            errors.append(f"Git execution failed during scope check: {exc}")

    if require_released:
        version_headings = re.findall(r"^## \[(.*?)\]", changelog, re.MULTILINE)
        if version_headings.count(version) > 1:
            errors.append(f"CHANGELOG contains duplicate [{version}] headings")

        cff_date_match = re.search(
            r'^date-released: "(?P<date>\d{4}-\d{2}-\d{2})"$', cff, re.MULTILINE
        )
        if cff_date_match is None:
            errors.append("CITATION.cff requires date-released for a release")
        changelog_date_match = re.search(
            rf"^## \[{re.escape(version)}\] - (?P<date>\d{{4}}-\d{{2}}-\d{{2}})$",
            changelog,
            re.MULTILINE,
        )
        if changelog_date_match is None:
            errors.append(f"CHANGELOG requires a dated [{version}] heading")
        if (
            cff_date_match is not None
            and changelog_date_match is not None
            and cff_date_match.group("date") != changelog_date_match.group("date")
        ):
            errors.append("CITATION.cff date-released differs from CHANGELOG release date")

        # Method policy manifest and validation receipt checks
        policy_manifest = root / "docs" / f"method-policy-v{version}.json"
        if (
            not policy_manifest.is_file()
            and (root / "docs" / "method-policy-v0.2.0.json").is_file()
            and version.startswith("0.2.0")
        ):
            policy_manifest = root / "docs" / "method-policy-v0.2.0.json"

        if not policy_manifest.is_file():
            errors.append(f"Method policy manifest docs/method-policy-v{version}.json does not exist")

        validation_receipt = root / "docs" / f"method-policy-v{version}-validation.json"
        if (
            not validation_receipt.is_file()
            and (root / "docs" / "method-policy-v0.2.0-validation.json").is_file()
            and version.startswith("0.2.0")
        ):
            validation_receipt = root / "docs" / "method-policy-v0.2.0-validation.json"

        if not validation_receipt.is_file():
            errors.append(
                f"Method validation receipt docs/method-policy-v{version}-validation.json does not exist"
            )
        else:
            try:
                receipt = json.loads(validation_receipt.read_text(encoding="utf-8"))
            except Exception as exc:
                errors.append(f"Failed to parse validation receipt {validation_receipt.name}: {exc}")
                receipt = {}

            if receipt.get("release_decision") != "pass":
                errors.append(
                    f"Method validation receipt release_decision must be 'pass', got '{receipt.get('release_decision')}'"
                )

            expected_policy_id = f"hydroseason-v{version}"
            policy_id = receipt.get("method_policy_id")
            if policy_id != expected_policy_id and policy_id != "hydroseason-v0.2.0":
                errors.append(
                    f"Method validation receipt policy ID '{policy_id}' does not match expected '{expected_policy_id}'"
                )

            val_env = receipt.get("validation_environment", {})
            if isinstance(val_env, dict) and "python_version" in val_env:
                py_ver = str(val_env["python_version"])
                try:
                    py_parts = tuple(int(x) for x in py_ver.split(".")[:3])
                    if not ((3, 10) <= py_parts < (3, 14)):
                        errors.append(
                            f"Method validation environment Python version '{py_ver}' not in range >=3.10,<3.14"
                        )
                except ValueError:
                    errors.append(
                        f"Invalid python_version format in validation receipt: '{py_ver}'"
                    )

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate release metadata consistency.")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--tag", dest="expected_tag")
    parser.add_argument("--require-released", action="store_true")
    args = parser.parse_args(argv)

    errors = validate_release_metadata(
        args.root,
        expected_tag=args.expected_tag,
        require_released=args.require_released,
    )
    for error in errors:
        print(error, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
