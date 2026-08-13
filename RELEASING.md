# Releasing HydroSeason

This is the maintainer runbook for publishing a HydroSeason release to
TestPyPI, PyPI, GitHub Releases, and Zenodo. It assumes the release-blocking
CI gates in [`.github/workflows/test.yml`](.github/workflows/test.yml) are
green on the commit being released.

## One-time external setup

Complete every item below **before** the first release. None of it is
automated by this repository's workflows.

1. **TestPyPI pending trusted publisher.** On https://test.pypi.org, register
   a pending trusted publisher for this project with:
   - Repository owner: `tayerthiaggo`
   - Repository name: `hydroseason`
   - Workflow name: `testpypi.yml`
   - Environment name: `testpypi`

2. **PyPI pending trusted publisher.** On https://pypi.org, register a
   pending trusted publisher for this project with:
   - Repository owner: `tayerthiaggo`
   - Repository name: `hydroseason`
   - Workflow name: `publish.yml`
   - Environment name: `pypi`

3. **Protected GitHub environments.** In the repository's Settings →
   Environments, create `testpypi` and `pypi`. Configure `pypi` with a
   required reviewer (human approval gate) before any deployment can run
   against it. `testpypi` may run without a reviewer since it never touches
   the immutable public index.

4. **Zenodo connection.** Connect this GitHub repository to Zenodo
   (https://zenodo.org/account/settings/github/) and enable archiving for
   `tayerthiaggo/hydroseason` before the release is published. Zenodo only
   archives GitHub Releases published after the repository was enabled.

5. **`CITATION.cff` present, `.zenodo.json` absent.** Confirm
   [`CITATION.cff`](CITATION.cff) exists and is valid, and that no
   `.zenodo.json` file has been added — Zenodo derives its metadata from
   `CITATION.cff` alone. Do not add `.zenodo.json` at any point in this
   process.

## Immutable-release discipline

- **No tag movement or file replacement after publication.** Once a tag is
  pushed and a GitHub Release is published, never delete, re-tag, or force-push
  over it, and never replace an uploaded asset in place.
- **A failed or discrepant candidate gets a new version**, not a patched
  re-upload. Before any file is uploaded, fixes may reuse the candidate
  version. Once TestPyPI or PyPI accepts any file, that project/version
  filename is permanently consumed; use a new prerelease or final version
  (for example `0.1.0rc2` or `0.1.1`) for corrections. Never mutate an
  uploaded version.

## Release steps

### 1. Prepare the release candidate — local

Freeze the release metadata and run the complete local gate:

```bash
# 1. Freeze metadata: pyproject version, CITATION.cff `version` +
#    `date-released`, and a dated `## [<version>] - YYYY-MM-DD` CHANGELOG
#    heading must all agree. Verify with:
python scripts/check_release_metadata.py --tag "v<version>" --require-released

# 2. Lint, lockfile, and tests
python -m ruff check hydroseason tests scripts
uv lock --check
python -m pytest -q -m "not experimental and not network and not performance" \
  --cov=hydroseason --cov-report=term-missing --cov-fail-under=80

# 3. Reproducibility gates (require the [all,docs,dev] extras)
python scripts/prepare_case_study_data.py --check
python scripts/_build_study_case_offline.py --check
python scripts/_build_study_case_rainfall.py --check
python scripts/run_resolution_case_study.py --check --output-dir case_studies/results/resolution
python scripts/render_case_study_docs.py --check
python scripts/check_notebook_05.py
python -m mkdocs build --strict

# 4. Build and verify artifacts
python -m build
python -m twine check dist/*
check-wheel-contents dist/*.whl
```

If any `--check` reports drift, re-run the same script without `--check` to
regenerate the checked results, review the diff, and commit it. Do not proceed
past this point until the release candidate is pushed and CI is green on it.

### 2. Publish and verify the TestPyPI candidate — human action

First merge the green release candidate into `main` without tagging or
publishing a release. Wait for the `docs.yml` Pages deployment to finish.
Then dispatch [`testpypi.yml`](.github/workflows/testpypi.yml) manually
(`workflow_dispatch`) with `ref` set to the exact merge commit SHA.

The workflow will:
- re-run every release gate (lint, lock, core tests with coverage, docs,
  build, metadata, wheel contents) against that exact commit;
- build the sdist/wheel once and upload them as a build artifact;
- publish through OIDC trusted publishing to TestPyPI (`testpypi`
  environment);
- install `hydroseason==<version>` from TestPyPI (with PyPI used only for
  dependencies TestPyPI does not mirror) in a clean environment and run the
  CSV/report smoke and the no-network DEA/cache-surface smoke.

After it finishes, manually confirm:
- the package version and metadata render correctly on
  https://test.pypi.org/project/hydroseason/;
- README links resolve (they point at the `main` branch and published docs
  site, not TestPyPI-relative paths);
- declared extras (`raster`, `stac`, `all`) install cleanly;
- the smoke jobs in the workflow run both passed.

**Do not proceed to Step 3 on any discrepancy.** If no file was uploaded,
fix the underlying issue, commit it, merge the updated candidate to `main`,
wait for the docs deployment, and dispatch the candidate again. If any file
was uploaded, consume that version and use a new version; never retry the
same filenames.

### 3. Merge, tag, and publish the GitHub Release — human action

Once the required CI checks pass on the release commit and Step 2 is clean:

1. Create an annotated tag on the exact `main` commit tested on TestPyPI:
   ```bash
   git tag -a v0.1.1 -m "HydroSeason 0.1.1" <merge-commit-sha>
   git push origin v0.1.1
   ```
2. Draft a GitHub Release from the tag, using the `[0.1.1]` section of
   `CHANGELOG.md` as the release body.
3. Before publishing, verify the draft's target commit matches the tag and
   that no additional commits have landed on `main` since.
4. Publish the release. This triggers
   [`publish.yml`](.github/workflows/publish.yml) on `release.published`,
   which:
   - re-validates tag/version/date/changelog agreement;
   - re-runs every release gate against the tagged commit;
   - builds the sdist/wheel once, builds
     `hydroseason-0.1.1-case-studies.zip` from the checked case-study
     results and docs, and uploads them as a build artifact;
   - waits for human approval on the `pypi` environment, then publishes the
     exact downloaded sdist/wheel to PyPI via OIDC trusted publishing;
   - uploads the identical sdist, wheel, and case-studies zip to the GitHub
     Release as assets.
5. When the `pypi` environment deployment is queued, a required reviewer
   must approve it in the Actions UI before publishing proceeds. Confirm the
   artifact being approved is the one built from the tagged commit (check
   the run's commit SHA) before approving.
6. Verify the wheel, sdist, and case-studies zip hashes attached to the
   GitHub Release match the artifact produced by the workflow run (compare
   `sha256sum` locally against the downloaded assets if in doubt).

Enabled Zenodo integration archives the published GitHub Release
automatically; no manual Zenodo action is required at this step.

### 4. Verify public services — human action

Once PyPI publishing completes:

- Fresh-install `hydroseason==0.1.1` from PyPI in a clean environment and run
  the documented CSV/report smoke from `README.md`.
- Check PyPI project metadata and rendered README at
  https://pypi.org/project/hydroseason/.
- Check GitHub Release assets (wheel, sdist, case-studies zip) download and
  hash-match.
- Check the deployed docs site (`docs.yml`) reflects the released version.
- Check Zenodo creator, version, and license metadata against
  `CITATION.cff` once the archive appears
  (https://zenodo.org/account/settings/github/) — this can take a few
  minutes after the GitHub Release is published.

### 5. Add the minted DOI — follow-up commit only

Only after Zenodo has minted a DOI for the archived release:

1. Add the real DOI to `CITATION.cff`, `docs/citation.md`, the README badge,
   and any other project URLs that reference it.
2. Commit this as a normal follow-up commit on `main`.
3. **Do not amend or move the `v0.1.1` tag** to attach the DOI commit — the
   DOI commit lands after the tag, as ordinary repository history.

## Never automated by this repository

The workflows in this repository never dispatch themselves, never tag,
never push, and never approve the `pypi` environment. Every action in this
document that is marked **human action** requires a maintainer to trigger it
explicitly through the GitHub UI or CLI.
