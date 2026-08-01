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
  re-upload. If TestPyPI verification (Step 2 below) finds any problem,
  fix it, bump nothing yet if the tag/release was never created, and start
  over. If a real tag or PyPI upload already happened and something is
  wrong, the fix is a new version (e.g. `0.1.1`), never mutating `0.1.0`.

## Release steps

### 1. Prepare the release candidate (Task 15, automated + local)

Freeze `CHANGELOG.md` and `CITATION.cff` release dates, run the complete
local gate, and commit the release candidate. See Task 15 of the release
readiness plan for the exact commands. Do not proceed past this point until
that commit is pushed and CI is green on it.

### 2. Publish and verify the TestPyPI candidate — human action

Dispatch [`testpypi.yml`](.github/workflows/testpypi.yml) manually
(`workflow_dispatch`) with `ref` set to the exact release commit SHA.

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

**Do not proceed to Step 3 on any discrepancy.** Fix the underlying issue,
commit the fix, and re-run Step 1 verification before trying TestPyPI again
(the release commit has not been tagged yet, so this is still safe to redo).

### 3. Merge, tag, and publish the GitHub Release — human action

Once the required CI checks pass on the release commit and Step 2 is clean:

1. Merge the release commit into `main` if it is not already there.
2. Create an annotated tag on the exact merge commit:
   ```bash
   git tag -a v0.1.0 -m "HydroSeason 0.1.0" <merge-commit-sha>
   git push origin v0.1.0
   ```
3. Draft a GitHub Release from the tag, using the `[0.1.0]` section of
   `CHANGELOG.md` as the release body.
4. Before publishing, verify the draft's target commit matches the tag and
   that no additional commits have landed on `main` since.
5. Publish the release. This triggers
   [`publish.yml`](.github/workflows/publish.yml) on `release.published`,
   which:
   - re-validates tag/version/date/changelog agreement;
   - re-runs every release gate against the tagged commit;
   - builds the sdist/wheel once, builds
     `hydroseason-0.1.0-case-studies.zip` from the checked case-study
     results and docs, and uploads them as a build artifact;
   - waits for human approval on the `pypi` environment, then publishes the
     exact downloaded sdist/wheel to PyPI via OIDC trusted publishing;
   - uploads the identical sdist, wheel, and case-studies zip to the GitHub
     Release as assets.
6. When the `pypi` environment deployment is queued, a required reviewer
   must approve it in the Actions UI before publishing proceeds. Confirm the
   artifact being approved is the one built from the tagged commit (check
   the run's commit SHA) before approving.
7. Verify the wheel, sdist, and case-studies zip hashes attached to the
   GitHub Release match the artifact produced by the workflow run (compare
   `sha256sum` locally against the downloaded assets if in doubt).

Enabled Zenodo integration archives the published GitHub Release
automatically; no manual Zenodo action is required at this step.

### 4. Verify public services — human action

Once PyPI publishing completes:

- Fresh-install `hydroseason==0.1.0` from PyPI in a clean environment and run
  the documented CSV/report smoke from `README.md`.
- Check PyPI project metadata and rendered README at
  https://pypi.org/project/hydroseason/.
- Check GitHub Release assets (wheel, sdist, case-studies zip) download and
  hash-match.
- Check the deployed docs site (`docs.yml`) reflects the released version.
- Run the exact-wheel HydroFragments integration check (Task 15, Step 3) if
  not already done against this artifact.
- Check Zenodo creator, version, and license metadata against
  `CITATION.cff` once the archive appears
  (https://zenodo.org/account/settings/github/) — this can take a few
  minutes after the GitHub Release is published.

### 5. Add the minted DOI — follow-up commit only

Only after Zenodo has minted a DOI for the archived release:

1. Add the real DOI to `CITATION.cff`, `docs/citation.md`, the README badge,
   and any other project URLs that reference it.
2. Commit this as a normal follow-up commit on `main`.
3. **Do not amend or move the `v0.1.0` tag** to attach the DOI commit — the
   DOI commit lands after the tag, as ordinary repository history.

## Never automated by this repository

The workflows in this repository never dispatch themselves, never tag,
never push, and never approve the `pypi` environment. Every action in this
document that is marked **human action** requires a maintainer to trigger it
explicitly through the GitHub UI or CLI.
