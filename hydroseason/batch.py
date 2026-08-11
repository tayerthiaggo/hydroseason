"""Row-preserving contracts and preflight for future multi-AOI workflows.

This module deliberately does not schedule or run work yet.  Optional
geospatial dependencies stay inside :func:`_prepare_batch_aois` so importing
the eventual public batch API remains available on a core installation.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

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
        if self.result is not None:
            valid = self.error_type is None and self.error_message is None
        else:
            valid = self.error_type is not None and self.error_message is not None
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
