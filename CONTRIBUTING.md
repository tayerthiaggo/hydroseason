# Contributing to HydroSeason

Thanks for your interest in improving HydroSeason. This guide covers the
development setup, testing, and the release process.

## Development setup

```bash
git clone https://github.com/tayerthiaggo/hydroseason.git
cd hydroseason
pip install -e ".[dev,docs,all]"
```

On Windows, GDAL/rasterio wheels can be fragile; `conda env create -f
environment.yml` installs the native stack from conda-forge first.

## Running the tests

The test suite requires Node.js 20 or newer for the real JavaScript interaction
test used by the offline manager report.

```bash
python -m pytest -q -n auto   # parallel; drop -n auto to run serially
```

Slow calibration-style checks are excluded by default; run them with
`-m slow`. Tests that need live DEA access are marked `network`.

Lint and docs:

```bash
python -m ruff check hydroseason tests scripts
python -m mkdocs build --strict
```

## Case-study reproducibility

The case-study inputs live in `case_studies/data/` and the checked results in
`tests/fixtures/v020/case_studies/`. After any change that can move results:

```bash
python scripts/prepare_case_study_data.py --check    # input data integrity
python scripts/_build_study_case_offline.py --check  # main workflow results
python scripts/_build_study_case_rainfall.py --check # rainfall-context results
python scripts/run_resolution_case_study.py --check  # resolution results
python scripts/render_case_study_docs.py --check     # docs tables match results
```

Drop `--check` to regenerate, review the diff, and commit it. After
regenerating, rebuild the example reports with
`python scripts/_build_docs_examples.py`.

## Coding conventions

- Public functions take keyword-only arguments after the leading DataFrame.
- Use modern type-annotation syntax (`int | None`, `tuple[...]`).
- Keep algorithm building blocks in their submodules; only re-export
  user-facing entry points from `hydroseason/__init__.py`.
- Add or update tests for any behaviour change.

## Release process

HydroSeason publishes to **TestPyPI** first, then **PyPI**, and archives the
release on GitHub and Zenodo. The full maintainer runbook — one-time trusted
publisher and environment setup, the TestPyPI verification gate, tagging and
publishing the GitHub Release, and the Zenodo DOI follow-up — lives in
[`RELEASING.md`](RELEASING.md). Every publish, tag, and environment approval
is a deliberate human action; no workflow in this repository dispatches,
tags, or publishes on its own.

A conda-forge submission starts only after the PyPI project exists and is
outside the PyPI/Zenodo release gate: after a PyPI release is live, open a PR
against the project's conda-forge feedstock (or
[staged-recipes](https://github.com/conda-forge/staged-recipes) for the
first submission) using the published PyPI sdist URL and real `sha256`.

### Verifying a build locally

```bash
python -m build
python -m twine check dist/*
check-wheel-contents dist/*.whl
```
