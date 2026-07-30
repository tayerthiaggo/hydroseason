# Cached WOfS Resolution Fidelity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Derive reusable 60/90/300 m WOfS caches from canonical local 30 m data and report strict exact-month hydrological-year fidelity, signal differences, storage, and local runtime.

**Architecture:** AOIs and native 30 m acquisition are prepared separately. The study runner is offline-only: it categorically block-reduces annual 30 m masks into factor-aligned derived Zarr stores, independently runs the production extent and hydrological-state pipeline at every resolution, then applies a pure strict comparator and writes CSV/JSON/self-contained HTML evidence.

**Tech Stack:** Python 3.10+, pandas, NumPy, Xarray, Dask Array, Zarr 2, rioxarray, Rasterio/Affine, GeoPandas/Shapely, HydroSeason dynamic-state pipeline, pytest.

## Global Constraints

- This plan depends on `2026-07-23-scalable-wofs-zarr-processing.md` being implemented and green.
- Source raster is a completed canonical 30 m WOfS cache; the comparison runner makes zero STAC calls.
- Study dates are exactly `2015-01-01` through `2025-12-31`.
- Resolutions are exactly `30`, `60`, `90`, and `300` m; factors are exactly `1`, `2`, `3`, and `10`.
- Non-integer factors are rejected.
- Coarsening operates on canonical monthly values, never raw WOfS bit fields.
- All-outside block becomes `-2`; outside is ignored otherwise; water requires `n_water > n_dry`; water/dry tie becomes dry; no valid water/dry inside AOI becomes `-1`.
- Edge padding uses `-2` and preserves the 30 m upper-left grid origin.
- Derived values remain exactly within `{-2,-1,0,1}`.
- Every resolution runs `monthly_water_extent` and `analyze_hydrological_state` independently with automatic pattern/configuration selection.
- A conclusive comparison requires at least five complete 30 m hydrological years.
- Strict equality requires identical complete `hy_year` sets, seasonal pattern, `hy_start`, `hy_end`, `peak_month`, and `trough_month`; no month tolerance is allowed.
- A scientifically unsafe 300 m result is reported as `fail`, not an execution failure.
- Screening covers all six existing lower-reach 50 km windows.
- Full-boundary validation covers Gilbert, Fitzroy WA, and Moonie.
- Construction time, cold local analysis, median of three warm analyses, graph/tasks, chunks, bytes, and peak RSS when available are recorded separately.
- Generated Zarr stores and reports remain under git-ignored `output/`.
- Default CI is deterministic and offline; the real cached matrix is opt-in.

---

## File Map

- Create `hydroseason/_study_aois.py`: reusable six-catchment metadata and lower-reach AOI construction.
- Modify `scripts/compare_catchment_resolution_windows.py`: import/re-export the extracted AOI helpers.
- Modify `tests/test_compare_catchment_resolution_windows.py`: preserve current behavior after extraction.
- Create `hydroseason/_io_wofs_coarsen.py`: exact categorical block reduction and derived-cache construction.
- Modify `hydroseason/_io_wofs_zarr.py`: derived-cache identity/provenance helper using the existing annual writer.
- Create `tests/test_io_wofs_coarsen.py`.
- Create `hydroseason/_resolution_fidelity.py`: pure strict HY comparator, signal metrics, artifact rows, and timing helpers.
- Create `tests/test_resolution_fidelity.py`.
- Create `scripts/prepare_resolution_fidelity_native_cache.py`: generate AOIs and acquire the 30 m sources as a distinct network stage.
- Create `scripts/run_cached_resolution_fidelity.py`: offline-only study orchestrator and artifacts.
- Create `tests/test_prepare_resolution_fidelity_native_cache.py`.
- Create `tests/test_run_cached_resolution_fidelity.py`.
- Create `tests/test_cached_resolution_fidelity_real.py`: opt-in cached-real matrix.
- Modify `pyproject.toml`: reuse `slow`, `network`, and `performance` markers from the optimization plan.
- Modify `docs/guide.md`: exact preparation, run, verdict, and artifact commands.

---

### Task 1: Extract Reusable Study AOI Construction

**Files:**
- Create: `hydroseason/_study_aois.py`
- Modify: `scripts/compare_catchment_resolution_windows.py`
- Modify: `tests/test_compare_catchment_resolution_windows.py`

**Interfaces:**
- Produces: `CatchmentSpec(key, display_name, river, region)` and the ordered `CATCHMENTS` tuple.
- Produces: `LowerReachWindow` with lower reach metadata and square/clipped AOIs.
- Produces: `build_lower_reach_window(key, boundary, streams, *, side_km=50.0, output_crs=3577)`.
- Produces: `study_aois(catchments_dir, output_dir, *, force=False) -> Sequence[StudyAOI]`, ordered as six lower windows then three full boundaries.

- [ ] **Step 1: Add exact study-matrix test**

Add to `tests/test_compare_catchment_resolution_windows.py`:

```python
def test_study_aoi_matrix_has_six_windows_and_three_full_boundaries(monkeypatch, tmp_path):
    import hydroseason._study_aois as study

    boundary = gpd.GeoDataFrame(
        {"area_km2": [200.0]}, geometry=[box(0, -1000, 100000, 1000)], crs="EPSG:3577"
    )
    streams = gpd.GeoDataFrame(
        {
            "hydroid": [1, 2], "nextdownid": [2, 999],
            "hierarchy": ["Major", "Major"], "upstrdarea": [10.0, 100.0],
        },
        geometry=[LineString([(0, 0), (50000, 0)]), LineString([(50000, 0), (90000, 0)])],
        crs="EPSG:3577",
    )
    monkeypatch.setattr(study, "_read_inputs", lambda root, key: (boundary, streams))
    aois = study.study_aois(tmp_path / "catchments", tmp_path / "aois")

    assert [a.key for a in aois[:6]] == [f"{spec.key}__lower50km" for spec in study.CATCHMENTS]
    assert [a.key for a in aois[6:]] == [
        "gilbert_river_qld__full",
        "fitzroy_river_wa__full",
        "moonie_river_qld_nsw__full",
    ]
    assert all(a.kind == "lower50km" for a in aois[:6])
    assert all(a.kind == "full" for a in aois[6:])
```

Reuse the file's existing `geopandas as gpd`, `LineString`, and `box` imports.

- [ ] **Step 2: Run and verify RED**

Run: `python -m pytest tests\test_compare_catchment_resolution_windows.py -q`

Expected: FAIL because `_study_aois` does not exist.

- [ ] **Step 3: Move helpers without behavior changes**

Move `CatchmentSpec`, `CATCHMENTS`, `LowerReachWindow`, `_geometry_union`, `_longest_linestring`, `_downstream_endpoint`, `_candidate_streams`, `select_lower_reach`, and `build_lower_reach_window` from the existing script into `hydroseason/_study_aois.py`. Keep their current bodies and ordering. In the script import these names at module scope so existing direct-script tests continue to resolve `mod.build_lower_reach_window`.

Add:

```python
@dataclass(frozen=True)
class StudyAOI:
    key: str
    display_name: str
    catchment_key: str
    kind: Literal["lower50km", "full"]
    path: Path


FULL_BOUNDARY_KEYS = (
    "gilbert_river_qld", "fitzroy_river_wa", "moonie_river_qld_nsw",
)
```

`study_aois` writes every generated AOI as EPSG:4326 GeoJSON under `output_dir`, uses existing ignored boundary/stream parquet inputs, and returns nine ordered `StudyAOI` records. It validates non-empty geometries and refuses to overwrite a path whose stored geometry digest differs unless `force=True`.

- [ ] **Step 4: Run existing and new AOI tests**

Run: `python -m pytest tests\test_compare_catchment_resolution_windows.py -q`

Expected: all current lower-window tests plus the nine-AOI matrix test PASS.

- [ ] **Step 5: Commit AOI extraction**

```powershell
git add hydroseason\_study_aois.py scripts\compare_catchment_resolution_windows.py tests\test_compare_catchment_resolution_windows.py
git commit -m "refactor: share resolution-study AOI construction"
```

---

### Task 2: Implement Exact Canonical Spatial Coarsening

**Files:**
- Create: `hydroseason/_io_wofs_coarsen.py`
- Create: `tests/test_io_wofs_coarsen.py`

**Interfaces:**
- Produces: `validate_resolution_factor(source_resolution: float, target_resolution: float) -> int`.
- Produces: `coarsen_canonical_mask(mask: DataArray, factor: int) -> DataArray`.
- Guarantees: same `time`, preserved upper-left grid origin, factor-scaled transform, ceil-divided spatial shape, lazy Dask data.

- [ ] **Step 1: Write categorical and georeferencing tests**

Create `tests/test_io_wofs_coarsen.py`:

```python
import numpy as np
import pandas as pd
import pytest
import xarray as xr

pytest.importorskip("dask")
pytest.importorskip("rioxarray")

from affine import Affine
from hydroseason._io_wofs_coarsen import coarsen_canonical_mask, validate_resolution_factor


def _mask(values) -> xr.DataArray:
    array = np.asarray(values, dtype=np.int8)
    if array.ndim == 2:
        array = array[None, :, :]
    time, height, width = array.shape
    transform = Affine(30, 0, 1000, 0, -30, 2000)
    return xr.DataArray(
        array,
        dims=("time", "y", "x"),
        coords={
            "time": pd.date_range("2015-01-01", periods=time, freq="MS"),
            "y": transform.f + (np.arange(height) + 0.5) * transform.e,
            "x": transform.c + (np.arange(width) + 0.5) * transform.a,
        },
        name="water_mask",
    ).rio.write_crs(3577).rio.write_transform(transform)


@pytest.mark.parametrize(
    "block,expected",
    [
        ([[1, 1], [1, 0]], 1),
        ([[0, 0], [1, -1]], 0),
        ([[1, 0], [-1, -2]], 0),
        ([[-1, -1], [-2, -2]], -1),
        ([[-2, -2], [-2, -2]], -2),
        ([[1, 1], [-2, -1]], 1),
    ],
)
def test_categorical_block_rules(block, expected):
    result = coarsen_canonical_mask(_mask([block]), factor=2).compute()
    assert result.item() == expected


@pytest.mark.parametrize("factor", [2, 3, 10])
def test_padding_preserves_origin_shape_transform_and_domain(factor):
    source = _mask(np.zeros((2, 7, 11), dtype=np.int8))
    result = coarsen_canonical_mask(source.chunk({"time": 1, "y": 4, "x": 4}), factor)
    assert result.shape == (2, int(np.ceil(7 / factor)), int(np.ceil(11 / factor)))
    assert result.rio.transform() == Affine(30, 0, 1000, 0, -30, 2000) * Affine.scale(factor)
    assert result.rio.crs.to_epsg() == 3577
    assert set(np.unique(result.compute())) <= {-2, -1, 0, 1}
    assert result.chunks is not None


def test_non_integer_resolution_factor_is_rejected():
    assert validate_resolution_factor(30, 90) == 3
    with pytest.raises(ValueError, match="integer multiple"):
        validate_resolution_factor(30, 100)
```

- [ ] **Step 2: Run and verify RED**

Run: `python -m pytest tests\test_io_wofs_coarsen.py -q`

Expected: FAIL because the coarsening module does not exist.

- [ ] **Step 3: Implement Dask-friendly class counts**

Validate `factor >= 1`, canonical input domain lazily at materialisation boundaries, regular unrotated transform, and `time/y/x` dimensions. Pad only the bottom and right edges:

```python
pad_y = (-mask.sizes["y"]) % factor
pad_x = (-mask.sizes["x"]) % factor
padded = mask.pad(y=(0, pad_y), x=(0, pad_x), constant_values=-2)
coarsen = {"y": factor, "x": factor}
water = (padded == 1).astype("uint16").coarsen(coarsen, boundary="exact").sum()
dry = (padded == 0).astype("uint16").coarsen(coarsen, boundary="exact").sum()
inside = (padded != -2).astype("uint16").coarsen(coarsen, boundary="exact").sum()
coarse = xr.where(
    inside == 0,
    np.int8(-2),
    xr.where(water > dry, np.int8(1), xr.where(dry > 0, np.int8(0), np.int8(-1))),
).astype(np.int8)
```

Assign Xarray's coarsened coordinates to centers derived from `out_transform = source_transform * Affine.scale(factor)`. Preserve time and non-conflicting attrs; write CRS and transform explicitly with rioxarray. Rechunk output to `time=1,y=512,x=512`.

- [ ] **Step 4: Run reducer tests**

Run: `python -m pytest tests\test_io_wofs_coarsen.py -q`

Expected: all categorical, factor, shape, transform, domain, and laziness tests PASS.

- [ ] **Step 5: Commit coarsener**

```powershell
git add hydroseason\_io_wofs_coarsen.py tests\test_io_wofs_coarsen.py
git commit -m "feat: coarsen canonical WOfS masks exactly"
```

---

### Task 3: Materialise Reusable Derived Resolution Caches

**Files:**
- Modify: `hydroseason/_io_wofs_zarr.py`
- Modify: `hydroseason/_io_wofs_coarsen.py`
- Modify: `tests/test_io_wofs_coarsen.py`

**Interfaces:**
- Produces: `DerivedCacheIdentity(source_identity: str, factor: int, reducer_version: int = 1)`.
- Produces: `derive_resolution_cache(source_handle, target_root, *, factor, overwrite=False) -> tuple[WOfSCacheHandle, dict]`.
- Derived manifest records source identity, factor, source/target resolution, reducer version, construction seconds, task count, chunks read/written, bytes, and digest.

- [ ] **Step 1: Add identity, resume, and no-STAC tests**

Append these imports, helper, and tests to `tests/test_io_wofs_coarsen.py`:

```python
import sys
from collections.abc import Sequence
from pathlib import Path
from unittest.mock import Mock

from hydroseason._io_wofs_coarsen import DerivedCacheIdentity, derive_resolution_cache
from hydroseason._io_wofs_zarr import (
    WOfSCacheIdentity,
    WOfSCacheRequest,
    create_cache_handle,
    write_annual_group,
)
from hydroseason._spatial_plan import GridWindow


def _source_handle(tmp_path: Path, *, years: Sequence[int]):
    request = WOfSCacheRequest(
        stac_url="https://example.invalid/stac", collection="ga_ls_wo_3",
        aoi_sha256="a" * 64, start_date=f"{min(years)}-01-01",
        end_date=f"{max(years)}-12-31", crs="EPSG:3577", resolution=30.0,
        classifier_version=1, groupby="solar_day", majority=True,
        planner_version=1, schema_version=1,
    )
    identity = WOfSCacheIdentity.from_request(
        request, shape=(4, 4), transform=(30, 0, 1000, 0, -30, 2000)
    )
    handle = create_cache_handle(tmp_path / "native", identity)
    for year in years:
        cube = _mask(np.zeros((12, 4, 4), dtype=np.int8)).assign_coords(
            time=pd.date_range(f"{year}-01-01", periods=12, freq="MS")
        )
        write_annual_group(
            handle, year, cube.chunk({"time": 1, "y": 4, "x": 4}),
            windows=(GridWindow("parent", 0, 4, 0, 4),), item_ids=(f"item-{year}",),
        )
    return handle


def test_derived_identity_includes_source_and_factor():
    assert DerivedCacheIdentity("a", 2).digest != DerivedCacheIdentity("a", 3).digest
    assert DerivedCacheIdentity("a", 2).digest != DerivedCacheIdentity("b", 2).digest


def test_derived_cache_resumes_completed_years(monkeypatch, tmp_path):
    source = _source_handle(tmp_path, years=(2015, 2016))
    writer = Mock(wraps=write_annual_group)
    monkeypatch.setattr("hydroseason._io_wofs_coarsen.write_annual_group", writer)
    first, _ = derive_resolution_cache(source, tmp_path / "derived", factor=2)
    second, _ = derive_resolution_cache(source, tmp_path / "derived", factor=2)
    assert first == second
    assert writer.call_count == 2


def test_corrupt_derived_year_is_rebuilt_from_local_source(monkeypatch, tmp_path):
    source = _source_handle(tmp_path, years=(2015,))
    target, _ = derive_resolution_cache(source, tmp_path / "derived", factor=2)
    (target.path / "years" / "2015" / "complete.json").unlink()
    writer = Mock(wraps=write_annual_group)
    monkeypatch.setattr("hydroseason._io_wofs_coarsen.write_annual_group", writer)
    rebuilt, _ = derive_resolution_cache(source, tmp_path / "derived", factor=2)
    assert rebuilt == target
    assert writer.call_count == 1


def test_derivation_does_not_import_or_call_stac(monkeypatch, tmp_path):
    source = _source_handle(tmp_path, years=(2015,))
    monkeypatch.setitem(sys.modules, "pystac_client", None)
    monkeypatch.setitem(sys.modules, "odc.stac", None)
    derive_resolution_cache(source, tmp_path / "derived", factor=3)
```

- [ ] **Step 2: Run and verify RED**

Run: `python -m pytest tests\test_io_wofs_coarsen.py -k "derived or derivation" -q`

Expected: FAIL because derived identity/cache functions do not exist.

- [ ] **Step 3: Implement derived identity and root creation**

Full digest is SHA-256 over canonical JSON:

```python
{
    "schema_version": 1,
    "source_identity": source_handle.identity,
    "factor": factor,
    "reducer_version": 1,
}
```

Create `target_root / f"{digest}.zarr"`; initialise the same root/manifest/index conventions as the 30 m cache, but mark `kind="derived_canonical_wofs"` and store no STAC endpoint/item list beyond inherited provenance.

- [ ] **Step 4: Coarsen and write one year at a time**

For each completed source year: open only that group, call `coarsen_canonical_mask`, create a full parent `GridWindow` for its ceil-divided shape, and call the existing `write_annual_group`. Completed target years are skipped unless `overwrite=True`. A corrupt target group is rebuilt locally from 30 m. Record graph tasks via `len(coarse.data.__dask_graph__())`, chunk count as `np.prod([len(axis) for axis in coarse.chunks])`, elapsed `perf_counter`, and recursive file bytes after completion.

- [ ] **Step 5: Run derived-cache tests**

Run: `python -m pytest tests\test_io_wofs_coarsen.py tests\test_io_wofs_zarr.py -q`

Expected: PASS; second derivation writes zero years and no STAC module is required.

- [ ] **Step 6: Commit derived cache**

```powershell
git add hydroseason\_io_wofs_zarr.py hydroseason\_io_wofs_coarsen.py tests\test_io_wofs_coarsen.py
git commit -m "feat: materialize reusable coarse WOfS caches"
```

---

### Task 4: Implement the Strict Hydrological-State Comparator

**Files:**
- Create: `hydroseason/_resolution_fidelity.py`
- Create: `tests/test_resolution_fidelity.py`

**Interfaces:**
- Produces: `StrictFidelityResult(verdict, native_complete_years, candidate_complete_years, pattern_match, mismatches)`.
- Produces: `compare_hydrological_states(native, candidate, *, candidate_resolution, min_complete_native=5) -> StrictFidelityResult`.
- Produces: `compare_extent_signals(native_extent, candidate_extent) -> dict`.

- [ ] **Step 1: Write one independent mismatch test per strict field**

Create `tests/test_resolution_fidelity.py`:

```python
from types import SimpleNamespace

import pandas as pd
import pytest

from hydroseason._resolution_fidelity import compare_hydrological_states


STRICT_FIELDS = ("hy_start", "hy_end", "peak_month", "trough_month")


def _complete_years(first: int, count: int) -> pd.DataFrame:
    years = list(range(first, first + count))
    return pd.DataFrame(
        {
            "hy_year": years,
            "status": "complete",
            "hy_start": pd.to_datetime([f"{year}-10-01" for year in years]),
            "hy_end": pd.to_datetime([f"{year + 1}-09-01" for year in years]),
            "peak_month": pd.to_datetime([f"{year + 1}-02-01" for year in years]),
            "trough_month": pd.to_datetime([f"{year + 1}-09-01" for year in years]),
        }
    )


def _state(*, pattern: str, years: pd.DataFrame):
    return SimpleNamespace(pattern=SimpleNamespace(pattern=pattern), hydro_years=years)


def test_exact_states_pass():
    native = _state(pattern="unimodal", years=_complete_years(2018, 5))
    result = compare_hydrological_states(native, native, candidate_resolution=60)
    assert result.verdict == "pass"
    assert result.mismatches == ()


@pytest.mark.parametrize("field", STRICT_FIELDS)
def test_each_date_field_mismatch_fails(field):
    native = _state(pattern="unimodal", years=_complete_years(2018, 5))
    changed = native.hydro_years.copy()
    changed.loc[0, field] = pd.Timestamp(changed.loc[0, field]) + pd.DateOffset(months=1)
    candidate = _state(pattern="unimodal", years=changed)
    result = compare_hydrological_states(native, candidate, candidate_resolution=90)
    assert result.verdict == "fail"
    assert result.mismatches[0]["field"] == field
    assert result.mismatches[0]["native"] != result.mismatches[0]["candidate"]


def test_pattern_missing_year_and_extra_year_fail_independently():
    native = _state(pattern="unimodal", years=_complete_years(2018, 5))
    pattern = _state(pattern="bimodal_complex", years=native.hydro_years)
    missing = _state(pattern="unimodal", years=native.hydro_years.iloc[:-1])
    extra = _state(pattern="unimodal", years=pd.concat([native.hydro_years, _complete_years(2023, 1)]))
    assert compare_hydrological_states(native, pattern, candidate_resolution=300).mismatches[0]["field"] == "pattern"
    assert any(m["kind"] == "missing_year" for m in compare_hydrological_states(native, missing, candidate_resolution=300).mismatches)
    assert any(m["kind"] == "extra_year" for m in compare_hydrological_states(native, extra, candidate_resolution=300).mismatches)


def test_fewer_than_five_native_complete_years_is_inconclusive():
    native = _state(pattern="unimodal", years=_complete_years(2018, 4))
    result = compare_hydrological_states(native, native, candidate_resolution=60)
    assert result.verdict == "inconclusive"
    assert result.native_complete_years == 4
```

- [ ] **Step 2: Run and verify RED**

Run: `python -m pytest tests\test_resolution_fidelity.py -q`

Expected: FAIL because the comparator module does not exist.

- [ ] **Step 3: Implement exact comparison**

Filter each frame to `status == "complete"`, sort by `hy_year`, and reject duplicate complete years. If native complete count is below five, return `inconclusive` before candidate comparison. Add mismatch records with keys:

```python
{
    "candidate_resolution_m": int(candidate_resolution),
    "hy_year": int(year) if year is not None else None,
    "kind": "value" | "pattern" | "missing_year" | "extra_year",
    "field": field,
    "native": serialised_native,
    "candidate": serialised_candidate,
}
```

Serialize dates as `%Y-%m-%d`. Compare timestamps with exact `pd.Timestamp` equality. Verdict is `pass` only when the mismatch tuple is empty.

- [ ] **Step 4: Implement secondary signal metrics**

Outer-align monthly frames and compare rows where both `extent_pct` values are finite. Run `prepare_monthly_extent` and `robust_scale` independently for native and candidate. Return compared count, Pearson correlation when at least two non-constant points exist, mean/max absolute difference, usable-month counts, native/candidate amplitude and noise plus deltas, median `n_valid`, mean `invalid_pct`, and water-pixel retention `candidate.n_water.sum()/native.n_water.sum()` when native water is positive. These values never affect the strict verdict.

- [ ] **Step 5: Run comparator tests**

Run: `python -m pytest tests\test_resolution_fidelity.py -q`

Expected: exact pass, four date failures, pattern/year failures, and inconclusive behavior all PASS.

- [ ] **Step 6: Commit strict comparison**

```powershell
git add hydroseason\_resolution_fidelity.py tests\test_resolution_fidelity.py
git commit -m "feat: compare WOfS hydrological states strictly"
```

---

### Task 5: Separate Native Acquisition from the Offline Study

**Files:**
- Create: `scripts/prepare_resolution_fidelity_native_cache.py`
- Create: `tests/test_prepare_resolution_fidelity_native_cache.py`
- Modify: `docs/guide.md`

**Interfaces:**
- Preparation generates nine AOI GeoJSONs and acquires exactly one 30 m cache for each selected AOI.
- Emits `output/resolution_fidelity/native_cache_index.json` mapping study AOI key to full cache identity/path.
- This script is the only network-enabled component of the fidelity study.

- [ ] **Step 1: Add preparation routing test**

Create `tests/test_prepare_resolution_fidelity_native_cache.py`:

```python
import importlib.util
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from hydroseason._io_wofs_zarr import WOfSCacheHandle
from hydroseason._study_aois import StudyAOI


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prepare_resolution_fidelity_native_cache.py"


@pytest.fixture()
def mod():
    spec = importlib.util.spec_from_file_location("prepare_resolution_fidelity_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


def _study_aoi(tmp_path, key):
    path = tmp_path / f"{key}.geojson"
    path.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")
    return StudyAOI(
        key=key, display_name=key, catchment_key="a",
        kind="full" if key.endswith("__full") else "lower50km", path=path,
    )


def _handle(tmp_path, identity):
    return WOfSCacheHandle(
        path=tmp_path / f"{identity}.zarr", identity=identity, request_digest=f"request-{identity}"
    )


def test_prepare_acquires_each_selected_aoi_once(monkeypatch, tmp_path):
    aois = (_study_aoi(tmp_path, "a__lower50km"), _study_aoi(tmp_path, "a__full"))
    monkeypatch.setattr(mod, "study_aois", Mock(return_value=aois))
    acquire = Mock(side_effect=[_handle(tmp_path, "one"), _handle(tmp_path, "two")])
    monkeypatch.setattr(mod, "acquire_wofs_cache", acquire)

    index = mod.prepare_native_caches(
        catchments_dir=tmp_path / "catchments",
        output_dir=tmp_path / "study",
        cache_root=tmp_path / "cache",
        only=None,
        force=False,
    )

    assert acquire.call_count == 2
    assert all(call.kwargs["resolution"] == 30.0 for call in acquire.call_args_list)
    assert all(call.args[3:5] == ("2015-01-01", "2025-12-31") for call in acquire.call_args_list)
    assert set(index) == {"a__lower50km", "a__full"}
```

- [ ] **Step 2: Run and verify RED**

Run: `python -m pytest tests\test_prepare_resolution_fidelity_native_cache.py -q`

Expected: FAIL because the preparation script does not exist.

- [ ] **Step 3: Implement preparation and atomic index**

Use the production DEA URL/collection, EPSG:3577, resolution `30.0`, and exact dates. Filter `--only` against study AOI keys. Call `acquire_wofs_cache` sequentially and write JSON atomically after every successful AOI so interruption preserves progress. Each record contains AOI digest/path, cache identity/path, requested dates, and completion timestamp. A failed AOI is recorded under `failures` and later AOIs continue; process exit is nonzero when failures exist.

- [ ] **Step 4: Document preparation command**

Add:

```powershell
python scripts\prepare_resolution_fidelity_native_cache.py
python scripts\prepare_resolution_fidelity_native_cache.py --only gilbert_river_qld__lower50km
```

State clearly that this stage uses DEA/STAC; the next runner is local-only.

- [ ] **Step 5: Run preparation tests**

Run: `python -m pytest tests\test_prepare_resolution_fidelity_native_cache.py -q`

Expected: PASS.

- [ ] **Step 6: Commit native preparation**

```powershell
git add scripts\prepare_resolution_fidelity_native_cache.py tests\test_prepare_resolution_fidelity_native_cache.py docs\guide.md
git commit -m "feat: prepare native caches for fidelity study"
```

---

### Task 6: Build the Offline Resolution Matrix Runner and Artifacts

**Files:**
- Create: `scripts/run_cached_resolution_fidelity.py`
- Create: `tests/test_run_cached_resolution_fidelity.py`

**Interfaces:**
- Produces one result per AOI/resolution from local caches.
- Writes per-AOI `extent_<res>m.csv`, `hydro_years_<res>m.csv`, `comparison.json`.
- Writes root `summary.csv`, `hy_mismatches.csv`, and `report.html`.

- [ ] **Step 1: Add zero-network, independent-analysis, and artifact tests**

Create `tests/test_run_cached_resolution_fidelity.py`:

```python
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from hydroseason._io_wofs_zarr import WOfSCacheHandle


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_cached_resolution_fidelity.py"


@pytest.fixture()
def mod():
    spec = importlib.util.spec_from_file_location("run_cached_resolution_fidelity_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


def _handle(tmp_path, identity):
    return WOfSCacheHandle(tmp_path / f"{identity}.zarr", identity, f"request-{identity}")


def _native_record(tmp_path):
    return {"cache_identity": "native", "cache_path": str(tmp_path / "native.zarr")}


def _mask_cube():
    return xr.DataArray(
        np.zeros((132, 2, 2), dtype=np.int8), dims=("time", "y", "x"),
        coords={"time": pd.date_range("2015-01-01", periods=132, freq="MS")},
    ).chunk({"time": 1, "y": 2, "x": 2})


def _extent_frame():
    index = pd.date_range("2015-01-01", periods=132, freq="MS")
    return pd.DataFrame(
        {
            "n_water": 1, "n_aoi": 4, "n_valid": 4, "n_invalid": 0,
            "n_wet_aoi": 4, "extent_pct": 25.0, "invalid_pct": 0.0,
            "wet_fill_pct": 25.0,
        }, index=index,
    )


def _result(resolution):
    years = pd.DataFrame(
        {
            "hy_year": range(2016, 2021), "status": "complete",
            "hy_start": pd.to_datetime([f"{year}-10-01" for year in range(2015, 2020)]),
            "hy_end": pd.to_datetime([f"{year}-09-01" for year in range(2016, 2021)]),
            "peak_month": pd.to_datetime([f"{year}-02-01" for year in range(2016, 2021)]),
            "trough_month": pd.to_datetime([f"{year}-09-01" for year in range(2016, 2021)]),
        }
    )
    return SimpleNamespace(
        pattern=SimpleNamespace(pattern="unimodal"),
        config=SimpleNamespace(expected_trough_month=9), hydro_years=years,
        monthly_condition=pd.DataFrame(), data_quality={"n_usable": 132},
        resolution=resolution,
    )


def _fake_derived_cache(source, target_root, *, factor, overwrite=False):
    return _handle(Path(target_root), f"factor-{factor}"), {
        "construction_seconds": 1.0, "task_count": 10,
        "chunks_read": 4, "chunks_written": 1, "bytes": 100,
    }


def test_runner_uses_local_cache_and_analyzes_each_resolution_independently(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "pystac_client", None)
    monkeypatch.setitem(sys.modules, "odc.stac", None)
    monkeypatch.setattr(mod, "_load_native_index", Mock(return_value={"toy": _native_record(tmp_path)}))
    monkeypatch.setattr(mod, "derive_resolution_cache", _fake_derived_cache)
    monkeypatch.setattr(mod, "open_completed_mask_cache", Mock(return_value=_mask_cube()))
    monkeypatch.setattr(mod, "monthly_water_extent", Mock(return_value=_extent_frame()))
    analyze = Mock(side_effect=[
        _result(resolution)
        for resolution in (30, 60, 90, 300)
        for _run in range(4)
    ])
    monkeypatch.setattr(mod, "analyze_hydrological_state", analyze)

    result = mod.run_study(
        native_index=tmp_path / "native.json", output_dir=tmp_path / "out",
        only=("toy",), warm_runs=3,
    )

    assert analyze.call_count == 16
    assert [row["resolution_m"] for row in result["summary"]] == [60, 90, 300]
    assert (tmp_path / "out" / "summary.csv").exists()
    assert (tmp_path / "out" / "hy_mismatches.csv").exists()
    assert (tmp_path / "out" / "toy" / "comparison.json").exists()


def test_failed_300m_fidelity_still_completes_report(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "_load_native_index", Mock(return_value={"toy": _native_record(tmp_path)}))
    monkeypatch.setattr(mod, "derive_resolution_cache", _fake_derived_cache)
    monkeypatch.setattr(mod, "open_completed_mask_cache", Mock(return_value=_mask_cube()))
    monkeypatch.setattr(mod, "monthly_water_extent", Mock(return_value=_extent_frame()))
    states = []
    for resolution in (30, 60, 90, 300):
        state = _result(resolution)
        if resolution == 300:
            state.hydro_years.loc[0, "peak_month"] += pd.DateOffset(months=1)
        states.extend([state, state])
    monkeypatch.setattr(mod, "analyze_hydrological_state", Mock(side_effect=states))
    result = mod.run_study(
        native_index=tmp_path / "native.json", output_dir=tmp_path / "out",
        only=("toy",), warm_runs=1,
    )
    row = next(row for row in result["summary"] if row["resolution_m"] == 300)
    assert row["verdict"] == "fail"
    assert (tmp_path / "out" / "report.html").exists()


def test_html_is_self_contained(tmp_path):
    report = {
        "summary": [{"aoi_key": "toy", "resolution_m": 60, "verdict": "pass"}],
        "mismatches": [], "series": {"toy": {30: [0.0, 1.0], 60: [0.0, 1.0]}},
    }
    html_path = mod.write_html_report(report, tmp_path / "report.html")
    text = html_path.read_text(encoding="utf-8").lower()
    assert "<svg" in text
    assert "<script src=" not in text
    assert "http://" not in text
    assert "https://" not in text
```

- [ ] **Step 2: Run and verify RED**

Run: `python -m pytest tests\test_run_cached_resolution_fidelity.py -q`

Expected: FAIL because the runner script does not exist.

- [ ] **Step 3: Implement one-resolution local analysis**

For resolution 30, use the native handle. For 60/90/300, call `derive_resolution_cache` with factors 2/3/10 once. For each completed store:

1. Open masks lazily for exact study dates.
2. Record graph tasks with `len(masks.data.__dask_graph__())` and estimated chunk count from `masks.chunks`.
3. Time `monthly_water_extent(masks, time_block=12)` as cold local analysis.
4. Call `analyze_hydrological_state(extent, n_bootstrap=200, random_state=0)` independently.
5. Repeat the open/extent/state sequence three times and store median warm seconds.
6. Write extent and full HY frames with stable date formatting.
7. SHA-256 stable CSV bytes for both outputs.

Do not reuse the 30 m `pattern` or `config` when analysing coarse candidates.

Wrap cold and warm computes in a Dask `Callback` whose `_pretask` stores unique source-read task keys beginning with `open_dataset-water_mask` or `from-zarr`; record that unique count as `measured_loaded_chunks`. Record `estimated_chunks` separately so scheduler fusion/version changes remain visible rather than causing a false equality assumption.

- [ ] **Step 4: Implement metrics and strict artifacts**

For each candidate, call `compare_hydrological_states` and `compare_extent_signals`. Summary rows contain AOI key/kind, source-cache identity, candidate resolution, verdict, selected patterns, serialised automatic detector configurations, complete/unresolved/partial HY counts and reason frequencies, usable-month counts, amplitude/noise and their change from 30 m, correlation, mean/max absolute difference, `n_valid`, `invalid_pct`, water-pixel retention, first mismatch, construction/cold/warm seconds, graph tasks, estimated/measured chunks, bytes, peak RSS or null, environment/package versions, extent digest, and HY digest. Flatten every mismatch with AOI metadata into `hy_mismatches.csv`. Always write headers even when no mismatches exist.

Write per-AOI `comparison.json` atomically after each candidate so an interrupted study resumes completed candidate identities. Write both `summary.csv` and machine-readable `summary.json`. Catch an execution exception per AOI, append its type/message to `failures.json`, and continue with remaining AOIs; strict scientific `fail` verdicts are ordinary successful rows and never enter `failures.json`.

- [ ] **Step 5: Implement optional peak-RSS sampler**

When `psutil` imports successfully, a daemon thread samples `Process().memory_info().rss` every 0.05 seconds between context-manager enter/exit and records the maximum. When import fails, record JSON `null`; do not add a required dependency.

- [ ] **Step 6: Implement self-contained HTML**

Generate plain HTML/CSS and inline SVG polylines for the four monthly extent series. Include a verdict matrix, performance/storage table, per-AOI strict mismatch table, and an explicit note that strict dates—not correlation—control pass/fail. Escape all text with `html.escape`; embed no CDN, external stylesheet, image, or script URL.

- [ ] **Step 7: Run runner tests**

Run: `python -m pytest tests\test_run_cached_resolution_fidelity.py -q`

Expected: PASS; no STAC imports, four independent analyses, failed 300 m retained, artifacts complete, HTML self-contained.

- [ ] **Step 8: Commit offline runner**

```powershell
git add scripts\run_cached_resolution_fidelity.py tests\test_run_cached_resolution_fidelity.py
git commit -m "feat: run cached WOfS resolution fidelity study"
```

---

### Task 7: Add Deterministic Workload Guards and Opt-In Cached-Real Matrix

**Files:**
- Modify: `tests/test_io_wofs_coarsen.py`
- Create: `tests/test_cached_resolution_fidelity_real.py`
- Modify: `docs/guide.md`

**Interfaces:**
- Default tests assert shape/chunk/task reductions without wall-clock assumptions.
- Opt-in test consumes existing local 30 m caches and performs no network access.

- [ ] **Step 1: Add deterministic pixel/workload assertions**

Append:

```python
@pytest.mark.parametrize("factor,expected_max_ratio", [(2, 0.26), (3, 0.12), (10, 0.011)])
def test_coarse_pixel_count_scales_by_factor_squared(factor, expected_max_ratio):
    source = _mask(np.zeros((12, 1000, 1000), dtype=np.int8)).chunk({"time": 1, "y": 500, "x": 500})
    coarse = coarsen_canonical_mask(source, factor)
    ratio = (coarse.sizes["y"] * coarse.sizes["x"]) / (source.sizes["y"] * source.sizes["x"])
    assert ratio <= expected_max_ratio
    assert len(coarse.data.__dask_graph__()) < len(source.data.__dask_graph__()) * factor * factor + 500
```

The task bound is structural and deliberately loose enough for Xarray/Dask version variation; it guards accidental full-resolution replication, not scheduler optimization.

- [ ] **Step 2: Add opt-in cached-real test**

Create `tests/test_cached_resolution_fidelity_real.py`:

```python
import json
import os
import subprocess
import sys

import pytest


@pytest.mark.slow
@pytest.mark.performance
def test_cached_real_resolution_matrix(tmp_path):
    if os.environ.get("HYDROSEASON_RUN_RESOLUTION_FIDELITY") != "1":
        pytest.skip("set HYDROSEASON_RUN_RESOLUTION_FIDELITY=1")
    native_index = os.environ.get(
        "HYDROSEASON_NATIVE_CACHE_INDEX",
        "output/resolution_fidelity/native_cache_index.json",
    )
    completed = subprocess.run(
        [
            sys.executable, "scripts/run_cached_resolution_fidelity.py",
            "--native-index", native_index,
            "--output-dir", str(tmp_path / "study"),
            "--warm-runs", "3",
        ],
        check=False, text=True, capture_output=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    rows = json.loads((tmp_path / "study" / "summary.json").read_text(encoding="utf-8"))
    assert len(rows) == 27
    assert {row["resolution_m"] for row in rows} == {60, 90, 300}
    assert all(row["verdict"] in {"pass", "fail", "inconclusive"} for row in rows)
    assert all(row["stac_calls"] == 0 for row in rows)
```

- [ ] **Step 3: Run default tests**

Run:

```powershell
python -m pytest tests\test_io_wofs_coarsen.py tests\test_resolution_fidelity.py tests\test_prepare_resolution_fidelity_native_cache.py tests\test_run_cached_resolution_fidelity.py tests\test_cached_resolution_fidelity_real.py -q
```

Expected: deterministic tests PASS; cached-real test SKIPPED.

- [ ] **Step 4: Run the local cached-real study**

After native preparation:

```powershell
$env:HYDROSEASON_RUN_RESOLUTION_FIDELITY='1'
python -m pytest tests\test_cached_resolution_fidelity_real.py -m "slow and performance" -v
```

Expected: 27 candidate rows (nine AOIs × three candidates), zero STAC calls, complete artifacts even where strict fidelity fails.

- [ ] **Step 5: Document interpretation**

In `docs/guide.md`, state:

- `pass`: exact pattern/year/date equality;
- `fail`: at least one strict mismatch, including scientifically unsafe 300 m;
- `inconclusive`: fewer than five complete native HYs;
- correlation/MAE are explanatory only;
- construction and cold/warm local analysis timings are separate;
- no production resolution changes automatically.

- [ ] **Step 6: Commit gates and documentation**

```powershell
git add tests\test_io_wofs_coarsen.py tests\test_cached_resolution_fidelity_real.py docs\guide.md
git commit -m "test: run cached WOfS resolution matrix"
```

---

## Final Verification

- [ ] Run `python -m pytest -q`; expected: all default tests PASS; network/performance studies SKIPPED.
- [ ] Run `git diff --check`; expected: no whitespace errors.
- [ ] Run `git status --short`; expected: only intentional implementation files; pre-existing user changes preserved.
- [ ] Run native preparation once and verify nine completed 30 m cache identities in `native_cache_index.json`.
- [ ] Disable network, run `python scripts\run_cached_resolution_fidelity.py`, and verify success with zero STAC imports/calls.
- [ ] Confirm derived stores exist for factors 2/3/10 and second run reuses them.
- [ ] Confirm `summary.csv` has 27 rows and `hy_mismatches.csv` contains exact native/candidate values for every failed field.
- [ ] Confirm each AOI directory contains four extent CSVs, four HY CSVs, and `comparison.json`.
- [ ] Open `report.html` without network and verify charts, timing/storage tables, strict verdict matrix, and mismatch evidence render.

## Completion Criteria

- 60/90/300 m stores are derived once from local 30 m canonical masks.
- Categorical block rules and origin-preserving edge padding are exact.
- The study runner makes zero STAC calls.
- All four resolutions run the production state pipeline independently.
- Strict exact-month matching covers pattern, complete-year set, HY start/end, peak, and trough/end-dry.
- Every conclusive AOI/candidate has `pass` or `fail`; insufficient native records are `inconclusive`.
- 300 m scientific failure does not abort execution.
- Six lower windows and three full boundaries are included.
- Construction, cold, warm, workload, storage, memory, and output digests are recorded.
- Generated artifacts remain ignored and reproducible.
