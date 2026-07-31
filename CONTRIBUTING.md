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

HydroSeason publishes `0.1.0` to **PyPI** and archives the release on GitHub
and Zenodo. A conda-forge submission starts only after the PyPI project exists
and is outside the `0.1.0` PyPI/Zenodo release gate.

1. Update the version in [`pyproject.toml`](pyproject.toml).
2. Move the relevant notes in [`CHANGELOG.md`](CHANGELOG.md) under the new
   version heading and set the date.
3. Commit, then tag and push:
   ```bash
   git commit -am "Release vX.Y.Z"
   git tag vX.Y.Z
   git push origin main --tags
   ```
4. Create a GitHub Release for the tag. This triggers
   [`.github/workflows/publish.yml`](.github/workflows/publish.yml), which
   builds the sdist/wheel, runs `twine check`, and publishes to PyPI via
   [trusted publishing](https://docs.pypi.org/trusted-publishers/) (configure
   the PyPI publisher and the `pypi` environment once, before the first
   release — no API token is stored).
5. **conda-forge**: after the PyPI release is live, open a PR against the
   project's conda-forge feedstock (or
   [staged-recipes](https://github.com/conda-forge/staged-recipes) for the
   first submission) using the published PyPI sdist URL and real `sha256`.

### Verifying a build locally

```bash
python -m build
python -m twine check dist/*
```
