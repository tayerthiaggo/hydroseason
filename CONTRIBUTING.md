# Contributing to HydroSeason

Thanks for your interest in improving HydroSeason. This guide covers the
development setup, testing, and the release process.

## Development setup

```bash
git clone https://github.com/tayerthiaggo/hydroseason.git
cd hydroseason
pip install -e ".[dev,docs,all]"
```

## Running the tests

```bash
python -m pytest -q
```

Optional checks:

```bash
ruff check hydroseason tests      # lint
python -m mkdocs build --strict   # docs build
```

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
