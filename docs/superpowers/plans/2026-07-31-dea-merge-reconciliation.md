# DEA Merge Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recover one coherent HydroSeason tree containing both completed release Tasks 1-9 and merge `36f3919`, validate the DEA acquisition/cache contracts, restore version `0.1.0`, and align HydroFragments with that release.

**Architecture:** Treat `HEAD` as source for merged DEA files and the live unstaged diff as source for post-Task-9 review fixes. Reconcile only named overlaps, then audit the statistics loader, conservative footprint, legacy pruning compatibility, cache identity, and dual-count path before building a `0.1.0` wheel for cross-repository integration.

**Tech Stack:** Git, Python 3.10-3.12, pandas, NumPy, xarray, Dask, odc-stac, pystac-client, rasterio, GeoPandas, Zarr, pytest, Ruff, uv, build, Twine.

## Global Constraints

- Release target is `0.1.0`; `0.1.1` was an unpublished coordination bump.
- Preserve all user changes. Never use `git reset --hard`, broad `git checkout`, or broad `git restore`.
- Before changing a file, inspect its staged and unstaged diffs independently.
- Full AOI defines scientific denominators. Analysis footprint only prunes I/O.
- Any uncertainty in a pruning source fails open to a full-AOI read.
- Default `wet_mask="off"` and `composite_bundle="legacy"` behavior stays compatible.
- Keep geospatial imports inside function bodies so core-only imports remain valid.
- Keep dependency direction `HydroFragments -> hydroseason`; never import HydroFragments in HydroSeason.
- Network and performance checks remain opt-in and outside ordinary CI.
- HydroSeason and HydroFragments changes receive separate commits in their respective repositories.
- Do not publish, tag, push, or create a release while executing this plan.

---

## File Map

### HydroSeason reconciliation

- Restore from `HEAD`: `hydroseason/_io_dea_stats.py`, `hydroseason/_io_geo.py`, `hydroseason/_io_wofs_acquire.py`, `hydroseason/_io_wofs_zarr.py`, `hydroseason/_spatial_plan.py`, `hydroseason/io.py`
- Restore from `HEAD`: `tests/test_io.py`, `tests/test_io_cache_footprints.py`, `tests/test_io_dea_stats.py`, `tests/test_io_wofs_acquire.py`, `tests/test_io_wofs_zarr.py`, `tests/test_spatial_plan.py`
- Reconcile explicitly: `hydroseason/__init__.py`, `tests/test_package_surface.py`
- Modify: `CITATION.cff`, `pyproject.toml`, `hydroseason/__init__.py`
- Modify as findings require: DEA/I/O files and their focused tests
- Modify: `docs/superpowers/plans/2026-07-27-wofs-wet-mask-pruning.md`
- Create: `docs/superpowers/audits/2026-07-31-dea-merge-audit.md`

### HydroFragments dependency alignment

- Modify: `D:/RLH/5.6/repos/HydroFragments/pyproject.toml`
- Modify: `D:/RLH/5.6/repos/HydroFragments/tests/output/test_manifest.py`
- Modify: `D:/RLH/5.6/repos/HydroFragments/tests/output/test_manifest_hydroseason.py`
- Modify: `D:/RLH/5.6/repos/HydroFragments/docs/superpowers/plans/2026-07-27-dea-zones-and-catchment-speed.md`

---

### Task 1: Reconcile the Live Index with Merge `36f3919`

**Files:**
- Restore/reconcile: exact HydroSeason files listed in the file map
- Preserve: all other staged, unstaged, and untracked files

**Interfaces:**
- Consumes: `HEAD=36f3919`, pre-merge release parent `c2a98ba`
- Produces: live code/test union containing merged DEA work plus post-Task-9 review assertions

- [ ] **Step 1: Record state and assert the known recovery preconditions**

Run:

```powershell
git rev-parse HEAD
git status --short
git diff --stat
git diff --cached --stat
git diff -- tests/test_package_surface.py
git diff --cached c2a98ba --quiet -- CITATION.cff hydroseason/__init__.py hydroseason/_io_dea_stats.py hydroseason/_io_geo.py hydroseason/_io_wofs_acquire.py hydroseason/_io_wofs_zarr.py hydroseason/_spatial_plan.py hydroseason/io.py pyproject.toml tests/test_io.py tests/test_io_cache_footprints.py tests/test_io_dea_stats.py tests/test_io_wofs_acquire.py tests/test_io_wofs_zarr.py tests/test_package_surface.py tests/test_spatial_plan.py
```

Expected: `HEAD` is `36f3919...`; final command exits 0. If either condition differs, stop and recompute the merge inventory instead of applying the commands below.

- [ ] **Step 2: Preserve the only staged/unstaged overlap explicitly**

Record that `tests/test_package_surface.py` must regain these names after restoration:

```python
"_detect_dynamic_hydrological_years_experimental",
"_find_semi_markov_trough_opportunities",
```

Also save `git diff -- tests/test_package_surface.py` in the task output contract. Do not create a broad stash containing unrelated work.

- [ ] **Step 3: Restore only the reverse-merge paths from `HEAD`**

Run the following as one path-scoped operation:

```powershell
git restore --source=HEAD --staged --worktree -- CITATION.cff hydroseason/__init__.py hydroseason/_io_dea_stats.py hydroseason/_io_geo.py hydroseason/_io_wofs_acquire.py hydroseason/_io_wofs_zarr.py hydroseason/_spatial_plan.py hydroseason/io.py pyproject.toml tests/test_io.py tests/test_io_cache_footprints.py tests/test_io_dea_stats.py tests/test_io_wofs_acquire.py tests/test_io_wofs_zarr.py tests/test_package_surface.py tests/test_spatial_plan.py
```

Expected: these paths no longer show staged reverse-merge deletions. All unrelated unstaged/untracked work remains present.

- [ ] **Step 4: Reapply the post-Task-9 package-surface assertion**

Add the two internal detector names from Step 2 to `internal_names` in `test_robust_extrema_and_semi_markov_internals_stay_unexported` without changing the merged public DEA exports.

- [ ] **Step 5: Prove the semantic union**

Run:

```powershell
python -m pytest tests/test_package_surface.py tests/test_spatial_plan.py tests/test_io.py tests/test_io_cache_footprints.py tests/test_io_dea_stats.py tests/test_io_wofs_acquire.py tests/test_io_wofs_zarr.py -q
git diff --check
git status --short
```

Expected: focused tests pass; `tests/test_io_cache_footprints.py` exists; top-level package exposes all four merged DEA/cache readers; unrelated work remains visible.

- [ ] **Step 6: Commit only the reconciliation**

```powershell
git add hydroseason/__init__.py hydroseason/_io_dea_stats.py hydroseason/_io_geo.py hydroseason/_io_wofs_acquire.py hydroseason/_io_wofs_zarr.py hydroseason/_spatial_plan.py hydroseason/io.py tests/test_io.py tests/test_io_cache_footprints.py tests/test_io_dea_stats.py tests/test_io_wofs_acquire.py tests/test_io_wofs_zarr.py tests/test_package_surface.py tests/test_spatial_plan.py
git commit -m "fix: reconcile DEA merge with release work"
```

Do not add metadata files yet; Task 2 resolves their version deliberately.

---

### Task 2: Restore the Authoritative `0.1.0` Version Contract

**Files:**
- Modify: `pyproject.toml`
- Modify: `CITATION.cff`
- Modify: `hydroseason/__init__.py`
- Test: `tests/test_release_metadata.py`
- Modify in HydroFragments: dependency/test/doc files named in the file map

**Interfaces:**
- Produces: one HydroSeason version source-of-truth value, `0.1.0`
- Produces: HydroFragments runtime requirement `hydroseason==0.1.0`

- [ ] **Step 1: Add a regression test for the repository version**

Add to `tests/test_release_metadata.py`:

```python
def test_first_remote_sensing_release_version_is_0_1_0():
    root = Path.cwd()
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["version"] == "0.1.0"
    assert 'version: "0.1.0"' in (root / "CITATION.cff").read_text(encoding="utf-8")
```

- [ ] **Step 2: Confirm merged metadata fails the new test**

Run: `python -m pytest tests/test_release_metadata.py -q`

Expected: FAIL while restored merge metadata still says `0.1.1`.

- [ ] **Step 3: Set all HydroSeason version surfaces to `0.1.0`**

Set:

```toml
version = "0.1.0"
```

in `pyproject.toml`, set `version: "0.1.0"` in `CITATION.cff`, and set the source-tree fallback to `__version__ = "0.1.0"` in `hydroseason/__init__.py`. Do not add `date-released` yet.

- [ ] **Step 4: Update HydroFragments dependency metadata**

In `D:/RLH/5.6/repos/HydroFragments/pyproject.toml`, replace:

```toml
"hydroseason==0.1.1",
```

with:

```toml
"hydroseason==0.1.0",
```

In automatic-version tests, use `hydroseason.__version__` for expected runtime provenance. Keep synthetic explicitly supplied version strings only where a test proves pass-through or mismatch behavior independent of the installed version.

- [ ] **Step 5: Correct the active HydroFragments plan**

Add a supersession note to `2026-07-27-dea-zones-and-catchment-speed.md`: HydroSeason APIs landed for the first public remote-sensing release `0.1.0`; its temporary `0.1.1` coordination pin is replaced by `hydroseason==0.1.0`. Preserve historical ledger text but change active install/release instructions.

- [ ] **Step 6: Verify both repositories**

HydroSeason:

```powershell
python scripts/check_release_metadata.py
python -m pytest tests/test_release_metadata.py tests/test_package_surface.py -q
```

HydroFragments:

```powershell
python -m pytest tests/output/test_manifest.py tests/output/test_manifest_hydroseason.py -q
```

Expected: all pass and active dependency metadata contains no `hydroseason==0.1.1`.

- [ ] **Step 7: Commit repositories separately**

HydroSeason:

```powershell
git add pyproject.toml CITATION.cff hydroseason/__init__.py tests/test_release_metadata.py
git commit -m "fix: retain first release version 0.1.0"
```

HydroFragments:

```powershell
git add pyproject.toml tests/output/test_manifest.py tests/output/test_manifest_hydroseason.py docs/superpowers/plans/2026-07-27-dea-zones-and-catchment-speed.md
git commit -m "fix: align hydroseason dependency with 0.1.0"
```

---

### Task 3: Make the DEA Statistics Loader Contract Truthful and Bounded

**Files:**
- Modify: `hydroseason/_io_dea_stats.py`
- Test: `tests/test_io_dea_stats.py`
- Modify: `hydroseason/io.py` and `hydroseason/__init__.py` only if the audit changes public names

**Interfaces:**
- Preserves: `open_wo_statistics(aoi, *, product, stac_url, resolution, crs, chunks) -> xr.Dataset`
- Preserves: `WoStatisticsUnavailable`
- Produces: bounded STAC search failure and truthful lazy-read environment contract

- [ ] **Step 1: Add a blocking-search timeout test**

Use a fake STAC search whose `items()` sleeps beyond a monkeypatched deadline:

```python
def test_open_wo_statistics_stops_waiting_after_search_deadline(monkeypatch, aoi):
    monkeypatch.setattr(dea_stats, "STAC_SEARCH_DEADLINE_S", 0.01)

    class Search:
        def items(self):
            time.sleep(0.2)
            return []

    monkeypatch.setattr(pystac_client.Client, "open", lambda *a, **k: FakeClient(Search()))
    with pytest.raises(WoStatisticsUnavailable, match="deadline"):
        open_wo_statistics(aoi)
```

- [ ] **Step 2: Confirm current elapsed-time check fails**

Run: `python -m pytest tests/test_io_dea_stats.py::test_open_wo_statistics_stops_waiting_after_search_deadline -q`

Expected: test takes about 0.2 seconds or returns only after the fake search completes.

- [ ] **Step 3: Apply the deadline to the blocking operation**

Open the client with explicit request timeouts and wrap item materialization:

```python
client = pystac_client.Client.open(
    stac_url,
    timeout=(STAC_CONNECT_TIMEOUT_S, STAC_READ_TIMEOUT_S),
)
search = client.search(collections=[product], bbox=bbox, limit=1000)
try:
    items = _run_with_timeout(lambda: list(search.items()), STAC_SEARCH_DEADLINE_S)
except TimeoutError as exc:
    raise WoStatisticsUnavailable(
        f"DEA Water Observation Statistics search exceeded the "
        f"{STAC_SEARCH_DEADLINE_S:g}s deadline"
    ) from exc
```

Remove the post-return elapsed-time claim. Document that Python cannot kill the orphaned request thread, but control returns to the caller at the deadline.

- [ ] **Step 4: Bind cloud-read configuration to lazy odc-stac reads**

Before `odc.stac.load`, configure odc-stac's own Rasterio environment, which is
retained for later Dask execution:

```python
odc.stac.configure_rio(
    cloud_defaults=True,
    aws={"aws_unsigned": True},
)
```

Keep the caller's ordinary process environment restoration. Remove the
HydroFragments workaround that imports `_configure_cog_read_env` only after
the exact built wheel passes its lazy-compute integration test.

Build a lazy local/mock COG-backed dataset inside `open_wo_statistics`, restore
the caller environment, then compute a cell. Assert the read succeeds after
the function has returned.

Required test assertion:

```python
result = open_wo_statistics(aoi)
assert hasattr(result["count_wet"].data, "compute")
assert result["count_wet"].isel(x=0, y=0).compute().item() >= 0
```

- [ ] **Step 5: Preserve source-tree import isolation and provenance**

Run tests proving core-only `import hydroseason` needs no raster/STAC packages, `frequency` remains `100 * count_wet / count_clear`, zero-clear pixels become NaN, and provenance records product, endpoint, item IDs, CRS, resolution, and time span.

- [ ] **Step 6: Run focused gates and commit**

```powershell
python -m pytest tests/test_io_dea_stats.py tests/test_io.py tests/test_package_surface.py -q
python -m ruff check hydroseason/_io_dea_stats.py tests/test_io_dea_stats.py
git add hydroseason/_io_dea_stats.py hydroseason/io.py hydroseason/__init__.py tests/test_io_dea_stats.py tests/test_package_surface.py
git commit -m "fix: bound and document DEA statistics loading"
```

---

### Task 4: Prove Conservative Planning, Cache Identity, and Dual Counts

**Files:**
- Modify as required: `hydroseason/_io_dea_stats.py`
- Modify as required: `hydroseason/_spatial_plan.py`
- Modify as required: `hydroseason/_io_geo.py`
- Modify as required: `hydroseason/_io_wofs_acquire.py`
- Modify as required: `hydroseason/_io_wofs_zarr.py`
- Test: `tests/test_io_dea_stats.py`
- Test: `tests/test_spatial_plan.py`
- Test: `tests/test_io_wofs_acquire.py`
- Test: `tests/test_io_wofs_zarr.py`
- Test: `tests/test_io_cache_footprints.py`
- Modify: `docs/superpowers/plans/2026-07-27-wofs-wet-mask-pruning.md`

**Interfaces:**
- Preserves: `build_wet_planning_footprint(...) -> WetPlanningFootprint`
- Preserves: `acquire_wofs_cache(..., planning_footprint=None, composite_bundle="legacy")`
- Preserves: `verify_cache_footprints` and `open_completed_dual_extent_counts`
- Produces: one documented recommended pruning path; legacy polygon route remains compatibility-only

- [ ] **Step 1: Add end-to-end raster-superset tests**

Parameterize isolated pixel, edge pixel, thin diagonal, thin orthogonal channel, and partial coarse block. For each shape:

```python
footprint = build_wet_planning_footprint(stats, requested_years=[2019], factor=4)
expanded = expand_to_native(footprint.coarse_mask, footprint.native_mask.shape)
assert np.all(~footprint.native_mask.values | expanded)

clipped_inside = rasterize_analysis_footprint_on_native_grid(footprint)
assert np.all(~footprint.native_mask.values | clipped_inside)
```

The second assertion covers conversion used by `_wet_aoi_from_planning_footprint`; coarse-window proof alone is insufficient.

- [ ] **Step 2: Add cache-identity separation tests**

Assert distinct request digests for:

```python
full = WOfSCacheRequest(**base)
legacy_pruned = WOfSCacheRequest(**base, wet_mask_sha256="a" * 64)
planned = WOfSCacheRequest(**base, footprint_digest="b" * 64, footprint_factor=4,
                           footprint_safety_cells=1, footprint_covered_years=(2019,))
dual = replace(planned, composite_bundle="hydrofragments_v1")
assert len({r.request_digest() for r in (full, legacy_pruned, planned, dual)}) == 4
```

Also retain the exact legacy-default digest regression.

- [ ] **Step 3: Add denominator and tamper tests**

Persist full-AOI and analysis-footprint geometry/count/digest. Verify:

- analysis pixel count may be smaller;
- reported extent denominator remains full AOI;
- changing either geometry, count, or digest makes `verify_cache_footprints` fail;
- missing footprint metadata fails for a pruned cache and remains valid for an unpruned legacy cache.

- [ ] **Step 4: Add one-graph dual-composite tests**

Instrument source graph construction and assert `composite_bundle="hydrofragments_v1"` performs one STAC query and one annual source graph, while writing both primary counts and `dual_extent_counts.json`. Assert `legacy` creates no dual sidecar and no extra computation.

- [ ] **Step 5: Fix only failures revealed by Steps 1-4**

Preferred order:

1. use active storage-aligned windows for coarse pruning;
2. use the proven native mask for fine clipping;
3. never buffer inward or resample with nearest/mean/mode;
4. if conversion cannot prove superset, disable pruning and warn rather than returning a smaller footprint.

Keep `wet_mask="dea_stats"` for compatibility in `0.1.0`, but label it legacy. Recommend caller-built `planning_footprint` for HydroFragments and new work.

- [ ] **Step 6: Resolve the old pruning plan explicitly**

Add a top banner to `2026-07-27-wofs-wet-mask-pruning.md`:

- polygon pruning tasks are compatibility history and are superseded for new callers by conservative max-pooled planning footprints;
- blake2b hashing, per-year STAC cache, empty-year fast path, and other independent write-path wins remain authoritative;
- default behavior remains unpruned.

- [ ] **Step 7: Run focused suites and commit**

```powershell
python -m pytest tests/test_io_dea_stats.py tests/test_spatial_plan.py tests/test_io_wofs_acquire.py tests/test_io_wofs_zarr.py tests/test_io_cache_footprints.py -q
python -m ruff check hydroseason tests
git add hydroseason/_io_dea_stats.py hydroseason/_spatial_plan.py hydroseason/_io_geo.py hydroseason/_io_wofs_acquire.py hydroseason/_io_wofs_zarr.py tests/test_io_dea_stats.py tests/test_spatial_plan.py tests/test_io_wofs_acquire.py tests/test_io_wofs_zarr.py tests/test_io_cache_footprints.py docs/superpowers/plans/2026-07-27-wofs-wet-mask-pruning.md
git commit -m "fix: verify conservative DEA acquisition footprints"
```

---

### Task 5: Restore Static Quality and Produce the Integrated Audit

**Files:**
- Modify: files reported by Ruff
- Create: `docs/superpowers/audits/2026-07-31-dea-merge-audit.md`

**Interfaces:**
- Produces: integrated green baseline consumed by the release-readiness continuation
- Produces: audit record containing commands, results, warning ledger, public API, and remaining risks

- [ ] **Step 1: Capture and fix all static failures**

Run:

```powershell
python -m ruff check hydroseason tests scripts
```

Known merge snapshot findings include import ordering in `_report_export.py`, `io.py`, `test_io.py`, `test_io_wofs_acquire.py`, `test_report_export.py`, and `test_spatial_plan.py`; unused imports; and import-position findings in `test_io_cache_footprints.py`. Apply mechanical fixes, then inspect every non-mechanical change.

- [ ] **Step 2: Run the complete offline reconciliation gate**

```powershell
python scripts/check_release_metadata.py
python -m ruff check hydroseason tests scripts
uv lock --check
python -m pytest -q -m "not experimental and not network and not performance"
python scripts/prepare_case_study_data.py --check
python -m mkdocs build --strict
```

Expected: all exit 0. Record warning categories and counts; do not hide them with blanket filters.

- [ ] **Step 3: Build and inspect `0.1.0` artifacts**

```powershell
python -m build
python -m twine check dist/*
check-wheel-contents dist/hydroseason-0.1.0-py3-none-any.whl
tar -tf dist/hydroseason-0.1.0.tar.gz
```

Expected: one wheel and one sdist for `0.1.0`; report assets included; case-study derived data excluded from PyPI artifacts as declared.

- [ ] **Step 4: Test the exact wheel from HydroFragments**

Create a fresh isolated environment, install the HydroSeason wheel, then install HydroFragments without replacing that dependency. Run:

```powershell
python -m pytest tests/io/test_dea.py tests/io/test_cache_footprints.py tests/integration/test_dea_workflow.py tests/temporal/test_hydroyear_adapter.py tests/output/test_manifest_hydroseason.py -q
```

Expected: all pass against installed `hydroseason==0.1.0`, not an editable sibling import.

- [ ] **Step 5: Write the audit record**

Include:

- commit and dirty-state boundaries;
- restored files and conflict resolutions;
- final version surfaces;
- public DEA/cache API list;
- legacy versus recommended pruning status;
- focused/full/build/HydroFragments command results;
- warning ledger;
- unresolved network/performance work explicitly handed to the release plan.

- [ ] **Step 6: Commit the integrated baseline**

```powershell
git add hydroseason tests scripts docs/superpowers/audits/2026-07-31-dea-merge-audit.md
git commit -m "chore: establish post-DEA release baseline"
```

---

## Final Success Checklist

- [ ] Live tree contains merge `36f3919` functionality and post-Task-9 review fixes
- [ ] No reverse-merge deletions remain staged
- [ ] HydroSeason reports `0.1.0` everywhere
- [ ] HydroFragments requires `hydroseason==0.1.0`
- [ ] `open_wo_statistics` failure timing and lazy-read environment contract are truthful
- [ ] Planning footprint remains a proven native wet-mask superset through fine clipping
- [ ] Full AOI remains scientific denominator
- [ ] Cache identities distinguish every acquisition mode
- [ ] Legacy defaults remain compatible
- [ ] Ruff, lock, offline tests, data check, strict docs, build, Twine, and wheel checks pass
- [ ] Exact built wheel passes HydroFragments integration tests
- [ ] Audit file provides a complete handoff to the release-readiness continuation
