from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]


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
    if require_released:
        if not re.search(r'^date-released: "\d{4}-\d{2}-\d{2}"$', cff, re.MULTILINE):
            errors.append("CITATION.cff requires date-released for a release")
        if not re.search(
            rf"^## \[{re.escape(version)}\] - \d{{4}}-\d{{2}}-\d{{2}}$",
            changelog,
            re.MULTILINE,
        ):
            errors.append(f"CHANGELOG requires a dated [{version}] heading")
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
