"""Memory-bounded outer scheduling for independent AOI work.

The scheduler intentionally controls only outer AOI concurrency.  It does
not change Dask or any inner-worker configuration: two outer workers provide
I/O overlap rather than twice the computational throughput.
"""

from __future__ import annotations

import math
import os
import warnings
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Callable, Literal, Sequence


@dataclass(frozen=True)
class BatchWorkItem:
    """One AOI payload and its conservatively estimated peak memory."""

    source_position: int
    estimated_peak_gb: float
    payload: object


def resolve_batch_resources(
    *, workers: Literal["auto"] | int, memory_budget_gb: float | None
) -> tuple[int, float]:
    """Resolve worker count and available memory budget for a batch.

    ``psutil`` is imported only when the caller asks for the automatic memory
    budget, keeping the core package importable without the STAC extra.
    """
    if workers == "auto":
        max_workers = min(2, os.cpu_count() or 1)
    elif isinstance(workers, bool) or not isinstance(workers, int):
        raise TypeError("workers must be 'auto' or a positive integer")
    elif workers < 1:
        raise ValueError("workers must be a positive integer")
    else:
        max_workers = workers

    if memory_budget_gb is None:
        try:
            import psutil
        except ImportError as exc:  # pragma: no cover - depends on installed extras
            raise ImportError(
                "Automatic memory budgeting requires psutil; install hydroseason[stac]."
            ) from exc
        budget_gb = 0.8 * (psutil.virtual_memory().available / 1_000_000_000)
    else:
        budget_gb = _validate_memory_budget(memory_budget_gb)

    return max_workers, budget_gb


def estimate_aoi_peak_gb(context) -> float:
    """Estimate one AOI's native-resolution peak working memory in decimal GB."""
    from ._io_resolution import plan_resolution

    _resolution_m, peak_gb, _floor_pp, _reason = plan_resolution(
        context.bounds_wgs84,
        "EPSG:3577",
        memory_budget_gb=float("inf"),
        candidate_res_m=(30.0,),
        bytes_per_scratch=5.0,
        time_chunk=12,
    )
    return peak_gb


def run_memory_bounded(
    items: Sequence[BatchWorkItem],
    worker: Callable[[object], object],
    *,
    max_workers: int,
    memory_budget_gb: float,
) -> dict[int, object | Exception]:
    """Run AOI work while admitting no more estimated memory than the budget.

    Work is largest-first to reduce fragmentation.  Items that exceed the
    whole budget are still run, but only when no other item is active.
    Exceptions from workers are retained per source row; ``BaseException``
    subclasses deliberately propagate for normal interruption semantics.
    """
    _validate_worker_count(max_workers)
    budget_gb = _validate_memory_budget(memory_budget_gb)
    validated_items = tuple(_validate_work_item(item) for item in items)
    _warn_for_oversized_items(validated_items, budget_gb)

    if max_workers == 1:
        return _run_serially(validated_items, worker)

    pending = deque(
        sorted(validated_items, key=lambda item: (-item.estimated_peak_gb, item.source_position))
    )
    active: dict[object, BatchWorkItem] = {}
    results: dict[int, object | Exception] = {}
    executor = ThreadPoolExecutor(max_workers=max_workers)
    try:
        while pending or active:
            running_peak_gb = sum(item.estimated_peak_gb for item in active.values())
            while pending and len(active) < max_workers:
                item = pending[0]
                is_oversized = item.estimated_peak_gb > budget_gb
                if active and (is_oversized or running_peak_gb + item.estimated_peak_gb > budget_gb):
                    break

                pending.popleft()
                future = executor.submit(worker, item.payload)
                active[future] = item
                running_peak_gb += item.estimated_peak_gb

            done, _not_done = wait(active, return_when=FIRST_COMPLETED)
            for future in done:
                item = active.pop(future)
                try:
                    results[item.source_position] = future.result()
                except Exception as exc:
                    results[item.source_position] = exc
    finally:
        executor.shutdown(wait=True, cancel_futures=True)

    return results


def _run_serially(
    items: Sequence[BatchWorkItem], worker: Callable[[object], object]
) -> dict[int, object | Exception]:
    """Run source-ordered work without constructing a thread executor."""
    results: dict[int, object | Exception] = {}
    for item in sorted(items, key=lambda item: item.source_position):
        try:
            results[item.source_position] = worker(item.payload)
        except Exception as exc:
            results[item.source_position] = exc
    return results


def _validate_worker_count(max_workers: int) -> None:
    if isinstance(max_workers, bool) or not isinstance(max_workers, int) or max_workers < 1:
        raise ValueError("max_workers must be a positive integer")


def _validate_memory_budget(memory_budget_gb: float) -> float:
    if isinstance(memory_budget_gb, bool) or not isinstance(memory_budget_gb, (int, float)):
        raise TypeError("memory_budget_gb must be a positive finite number")
    budget_gb = float(memory_budget_gb)
    if not math.isfinite(budget_gb) or budget_gb <= 0:
        raise ValueError("memory_budget_gb must be a positive finite number")
    return budget_gb


def _validate_work_item(item: BatchWorkItem) -> BatchWorkItem:
    if not isinstance(item, BatchWorkItem):
        raise TypeError("items must contain BatchWorkItem instances")
    if isinstance(item.estimated_peak_gb, bool) or not isinstance(item.estimated_peak_gb, (int, float)):
        raise TypeError("estimated_peak_gb must be a finite non-negative number")
    if not math.isfinite(item.estimated_peak_gb) or item.estimated_peak_gb < 0:
        raise ValueError("estimated_peak_gb must be a finite non-negative number")
    return item


def _warn_for_oversized_items(items: Sequence[BatchWorkItem], budget_gb: float) -> None:
    oversized_positions = sorted(
        item.source_position for item in items if item.estimated_peak_gb > budget_gb
    )
    if oversized_positions:
        positions = ", ".join(str(position) for position in oversized_positions)
        warnings.warn(
            (
                f"Estimated peak memory exceeds the {budget_gb:.1f} GB batch budget for "
                f"source positions {positions}; each will run alone."
            ),
            UserWarning,
            stacklevel=3,
        )


__all__ = [
    "BatchWorkItem",
    "estimate_aoi_peak_gb",
    "resolve_batch_resources",
    "run_memory_bounded",
]
