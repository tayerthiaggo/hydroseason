"""Row-preserving contracts and execution for multi-AOI workflows.

This module deliberately does not schedule or run work yet.  Optional
geospatial dependencies stay inside :func:`_prepare_batch_aois` so importing
the eventual public batch API remains available on a core installation.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Literal, Mapping

from ._batch_scheduler import (
    BatchWorkItem,
    estimate_aoi_peak_gb,
    resolve_batch_resources,
    run_memory_bounded,
)
from ._progress import ProgressEvent, resolve_progress_reporter
from ._workflow_input import DEFAULT_STAC_COLLECTION, DEFAULT_STAC_URL
from .workflow import _resolve_show_map, run_hydroseason

if TYPE_CHECKING:
    from ._aoi_context import AOIContext
    from .workflow import HydroSeasonRunResult


@dataclass(frozen=True)
class HydroSeasonAOIOutcome:
    """The successful result or captured exception for one source AOI row."""

    id: str
    source_position: int
    result: HydroSeasonRunResult | None
    error_type: str | None
    error_message: str | None

    def __post_init__(self) -> None:
        has_error_type = isinstance(self.error_type, str) and bool(self.error_type.strip())
        has_error_message = isinstance(self.error_message, str) and bool(self.error_message.strip())
        if self.result is not None:
            valid = self.error_type is None and self.error_message is None
        else:
            valid = has_error_type and has_error_message
        if not valid:
            raise ValueError("an outcome requires a result or complete error details, but not both")

    @property
    def succeeded(self) -> bool:
        """Whether this AOI completed without an exception."""
        return self.result is not None


class HydroSeasonBatchError(RuntimeError):
    """Raised when a batch contains one or more failed AOI outcomes."""

    def __init__(self, failures: tuple[HydroSeasonAOIOutcome, ...]):
        self.failures = failures
        summary = "; ".join(f"{item.id} ({item.error_type})" for item in failures)
        super().__init__(f"HydroSeason batch failed: {summary}")


@dataclass(frozen=True)
class HydroSeasonBatchResult:
    """Immutable, source-ordered outcomes from a future batch workflow."""

    outcomes: tuple[HydroSeasonAOIOutcome, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.outcomes, tuple):
            raise TypeError("outcomes must be a tuple")

    @property
    def succeeded(self) -> tuple[HydroSeasonAOIOutcome, ...]:
        """Successful outcomes in their original source order."""
        return tuple(item for item in self.outcomes if item.succeeded)

    @property
    def failed(self) -> tuple[HydroSeasonAOIOutcome, ...]:
        """Failed outcomes in their original source order."""
        return tuple(item for item in self.outcomes if not item.succeeded)

    def raise_for_failures(self) -> None:
        """Raise a single error covering every failed AOI, if any."""
        failures = self.failed
        if failures:
            raise HydroSeasonBatchError(failures)


@dataclass(frozen=True)
class _PreparedAOI:
    """A validated single source row with its future worker paths."""

    id: str
    safe_id: str
    source_position: int
    gdf: object
    context: AOIContext
    output_dir: Path
    cache_dir: Path | None


def run_hydroseason_many(
    aois,
    *,
    output_dir: str | Path,
    start_date,
    end_date,
    id_col: str | None = None,
    workers: Literal["auto"] | int = "auto",
    memory_budget_gb: float | None = None,
    show_map: Literal["auto"] | bool = "auto",
    fetch_rainfall: bool = False,
    stac_url: str = DEFAULT_STAC_URL,
    stac_collection: str = DEFAULT_STAC_COLLECTION,
    cache_dir: str | Path | None = None,
    analysis_options: Mapping[str, Any] | None = None,
    report_title: str | None = None,
    report_subtitle: str | None = None,
    progress: bool | Callable[[ProgressEvent], None] = False,
    refresh_historical_mask: bool = True,
) -> HydroSeasonBatchResult:
    """Run the public single-AOI workflow once for every source AOI row."""
    output_root = _validate_path(output_dir, name="output_dir")
    cache_root = (
        None if cache_dir is None else _validate_path(cache_dir, name="cache_dir")
    )
    _validate_date_range(start_date, end_date)
    show_preview = _resolve_show_map(show_map)
    reporter = resolve_progress_reporter(progress)

    prepared = _prepare_batch_aois(
        aois,
        output_dir=output_root,
        cache_dir=cache_root,
        id_col=id_col,
    )
    max_workers, memory_budget = resolve_batch_resources(
        workers=workers, memory_budget_gb=memory_budget_gb
    )

    if show_preview:
        _display_batch_preview(prepared)

    work_items = tuple(
        BatchWorkItem(
            item.source_position,
            estimate_aoi_peak_gb(item.context),
            item,
        )
        for item in prepared
    )
    results = run_memory_bounded(
        work_items,
        lambda item: _run_prepared_aoi(
            item,
            start_date=start_date,
            end_date=end_date,
            fetch_rainfall=fetch_rainfall,
            stac_url=stac_url,
            stac_collection=stac_collection,
            analysis_options=analysis_options,
            report_title=report_title,
            report_subtitle=report_subtitle,
            reporter=reporter,
            refresh_historical_mask=refresh_historical_mask,
        ),
        max_workers=max_workers,
        memory_budget_gb=memory_budget,
    )
    return HydroSeasonBatchResult(
        tuple(_as_outcome(item, results[item.source_position]) for item in prepared)
    )


def _validate_path(value: str | Path, *, name: str) -> Path:
    if isinstance(value, str) and not value.strip():
        raise ValueError(f"{name} must not be blank.")
    try:
        return Path(value)
    except TypeError as exc:
        raise TypeError(f"{name} must be a path-like value.") from exc


def _validate_date_range(start_date, end_date) -> None:
    import pandas as pd

    try:
        start = pd.Timestamp(start_date)
        end = pd.Timestamp(end_date)
    except (TypeError, ValueError) as exc:
        raise ValueError("start_date and end_date must be valid dates.") from exc
    if pd.isna(start) or pd.isna(end):
        raise ValueError("start_date and end_date must be valid dates.")
    if start > end:
        raise ValueError("start_date must not be after end_date.")


def _display_batch_preview(prepared: tuple[_PreparedAOI, ...]) -> None:
    """Best-effort one-map preview for the complete, row-preserving batch."""
    import pandas as pd

    from ._aoi_context import build_aoi_context
    from ._aoi_map import display_aoi_map

    try:
        all_rows = pd.concat([item.gdf for item in prepared], ignore_index=True)
        context = build_aoi_context(
            all_rows,
            labels=[item.safe_id for item in prepared],
        )
        display_aoi_map(context)
    except Exception as exc:
        warnings.warn(
            f"Could not display batch AOI map: {exc}", UserWarning, stacklevel=2
        )


def _run_prepared_aoi(
    item: _PreparedAOI,
    *,
    start_date,
    end_date,
    fetch_rainfall: bool,
    stac_url: str,
    stac_collection: str,
    analysis_options: Mapping[str, Any] | None,
    report_title: str | None,
    report_subtitle: str | None,
    reporter,
    refresh_historical_mask: bool,
):
    return run_hydroseason(
        None,
        output_dir=item.output_dir,
        aoi=item.gdf,
        aoi_name=item.id,
        start_date=start_date,
        end_date=end_date,
        fetch_rainfall=fetch_rainfall,
        stac_url=stac_url,
        stac_collection=stac_collection,
        cache_dir=item.cache_dir,
        analysis_options=analysis_options,
        report_title=report_title,
        report_subtitle=report_subtitle,
        progress=_prefixed_reporter(item.id, reporter),
        show_map=False,
        refresh_historical_mask=refresh_historical_mask,
    )


def _prefixed_reporter(item_id: str, reporter):
    def report(event: ProgressEvent) -> None:
        reporter(replace(event, label=f"{item_id}: {event.label}"))

    return report


def _as_outcome(item: _PreparedAOI, value: object | Exception) -> HydroSeasonAOIOutcome:
    if isinstance(value, Exception):
        return HydroSeasonAOIOutcome(
            item.id,
            item.source_position,
            None,
            type(value).__name__,
            str(value) or repr(value),
        )
    return HydroSeasonAOIOutcome(
        item.id,
        item.source_position,
        value,
        None,
        None,
    )


def _prepare_batch_aois(
    aois,
    *,
    output_dir: str | Path,
    cache_dir: str | Path | None = None,
    id_col: str | None = None,
) -> tuple[_PreparedAOI, ...]:
    """Validate and split a multi-row AOI source without touching child paths.

    The full source is loaded once, then every source row becomes exactly one
    prepared AOI.  Directory creation belongs to the later execution layer;
    preflight only calculates its per-row locations.
    """
    from . import io
    from ._aoi_context import build_aoi_context
    from ._report_export import safe_stem

    frame = io.load_aoi(aois)
    if frame.crs is None:
        raise ValueError("AOI GeoDataFrame must define a CRS.")
    if id_col is not None and id_col not in frame.columns:
        raise ValueError(f"AOI id column {id_col!r} is not present.")

    output_root = Path(output_dir)
    cache_root = Path(cache_dir) if cache_dir is not None else None
    ids = _resolve_ids(frame, id_col=id_col)
    safe_ids = tuple(safe_stem(value) for value in ids)
    _reject_duplicates(ids, label="AOI IDs")
    _reject_duplicates(safe_ids, label="safe AOI IDs")

    prepared = []
    for position, (item_id, safe_id) in enumerate(zip(ids, safe_ids, strict=True)):
        row = frame.iloc[[position]].copy()
        prepared.append(
            _PreparedAOI(
                id=item_id,
                safe_id=safe_id,
                source_position=position,
                gdf=row,
                context=build_aoi_context(row, display_name=item_id),
                output_dir=output_root / safe_id,
                cache_dir=cache_root / safe_id if cache_root is not None else None,
            )
        )
    return tuple(prepared)


def _resolve_ids(frame, *, id_col: str | None) -> tuple[str, ...]:
    """Return explicit cleaned IDs or stable row-position defaults."""
    if id_col is None:
        return tuple(f"aoi-{position:04d}" for position in range(1, len(frame) + 1))

    import pandas as pd

    resolved = []
    for position, value in enumerate(frame[id_col]):
        if bool(pd.isna(value)):
            raise ValueError(f"AOI ID at source position {position} is null.")
        item_id = str(value).strip()
        if not item_id:
            raise ValueError(f"AOI ID at source position {position} is blank.")
        resolved.append(item_id)
    return tuple(resolved)


def _reject_duplicates(values: tuple[str, ...], *, label: str) -> None:
    """Reject ambiguous identifiers before any row is handed to a worker."""
    if len(set(values)) != len(values):
        raise ValueError(f"{label} must be unique.")
