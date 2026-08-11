"""Contract tests for the global memory-aware AOI scheduler."""

from __future__ import annotations

import importlib
import math
import sys
from dataclasses import FrozenInstanceError
from threading import Lock

import pytest


def _item(position: int, peak_gb: float, payload: object | None = None):
    from hydroseason._batch_scheduler import BatchWorkItem

    return BatchWorkItem(position, peak_gb, position if payload is None else payload)


def test_scheduler_module_import_keeps_optional_dependencies_lazy(monkeypatch):
    """Eager psutil or pyproj imports would break a core-only installation."""
    module_name = "hydroseason._batch_scheduler"
    package = importlib.import_module("hydroseason")
    with monkeypatch.context() as isolated:
        isolated.delitem(sys.modules, module_name, raising=False)
        isolated.setitem(sys.modules, "psutil", None)
        isolated.setitem(sys.modules, "pyproj", None)

        module = importlib.import_module(module_name)

    package._batch_scheduler = sys.modules[module_name]
    assert module.__name__ == module_name
    assert package._batch_scheduler is sys.modules[module_name]


def test_batch_work_item_is_immutable_and_keeps_scheduler_fields():
    """Changing an item's position, estimate, or payload must not be possible in flight."""
    item = _item(3, 1.25, "alpha")

    assert (item.source_position, item.estimated_peak_gb, item.payload) == (3, 1.25, "alpha")
    with pytest.raises(FrozenInstanceError):
        item.estimated_peak_gb = 2.0


def test_resolve_batch_resources_uses_two_workers_and_exact_decimal_gb(monkeypatch):
    """Using binary GB or all CPUs would make the default resource envelope wrong."""
    from hydroseason import _batch_scheduler

    class _Memory:
        available = 8_000_000_000

    class _Psutil:
        @staticmethod
        def virtual_memory():
            return _Memory()

    monkeypatch.setitem(sys.modules, "psutil", _Psutil())
    monkeypatch.setattr(_batch_scheduler.os, "cpu_count", lambda: 12)

    assert _batch_scheduler.resolve_batch_resources(workers="auto", memory_budget_gb=None) == (2, 4.8)


def test_resolve_batch_resources_honours_explicit_values_without_psutil(monkeypatch):
    """An explicit resource configuration must not need the optional monitor package."""
    from hydroseason import _batch_scheduler

    monkeypatch.setitem(sys.modules, "psutil", None)

    assert _batch_scheduler.resolve_batch_resources(workers=1, memory_budget_gb=3.25) == (1, 3.25)


@pytest.mark.parametrize("workers", [True, False, 0, -1, 1.0, "1", None])
def test_resolve_batch_resources_rejects_invalid_worker_counts(workers):
    """Accepting a non-positive or boolean worker count would make scheduling ambiguous."""
    from hydroseason._batch_scheduler import resolve_batch_resources

    with pytest.raises((TypeError, ValueError)):
        resolve_batch_resources(workers=workers, memory_budget_gb=1.0)


@pytest.mark.parametrize("budget", [True, 0.0, -1.0, math.inf, -math.inf, math.nan])
def test_resolve_batch_resources_rejects_invalid_explicit_budgets(budget):
    """A non-finite or non-positive budget cannot provide a safe admission limit."""
    from hydroseason._batch_scheduler import resolve_batch_resources

    with pytest.raises((TypeError, ValueError)):
        resolve_batch_resources(workers=1, memory_budget_gb=budget)


def test_estimate_aoi_peak_is_monotonic_and_matches_the_resolution_planner():
    """Changing the fixed native-resolution estimate must preserve its planner contract."""
    pytest.importorskip("pyproj")
    from hydroseason._aoi_context import AOIContext
    from hydroseason._batch_scheduler import estimate_aoi_peak_gb
    from hydroseason._io_resolution import plan_resolution

    smaller = AOIContext("{}", (115.0, -32.0, 116.0, -31.0), "small", 1)
    fitzroy_scale = AOIContext("{}", (115.0, -32.0, 119.0, -29.0), "Fitzroy", 1)
    expected = plan_resolution(
        fitzroy_scale.bounds_wgs84,
        "EPSG:3577",
        memory_budget_gb=float("inf"),
        candidate_res_m=(30.0,),
        bytes_per_scratch=5.0,
        time_chunk=12,
    )[1]

    assert estimate_aoi_peak_gb(smaller) < estimate_aoi_peak_gb(fitzroy_scale)
    assert estimate_aoi_peak_gb(fitzroy_scale) == expected
    assert 9.0 < expected < 12.0
    assert expected > 4.8


def test_run_memory_bounded_runs_serially_in_source_order_without_an_executor(monkeypatch):
    """Serial mode must not reorder work or construct a thread pool."""
    from hydroseason import _batch_scheduler

    class _UnexpectedExecutor:
        def __init__(self, *args, **kwargs):
            raise AssertionError("serial scheduling must not create an executor")

    seen = []
    monkeypatch.setattr(_batch_scheduler, "ThreadPoolExecutor", _UnexpectedExecutor)

    results = _batch_scheduler.run_memory_bounded(
        [_item(2, 0.8, "third"), _item(0, 0.2, "first"), _item(1, 0.5, "second")],
        lambda payload: seen.append(payload) or payload.upper(),
        max_workers=1,
        memory_budget_gb=1.0,
    )

    assert seen == ["first", "second", "third"]
    assert results == {0: "FIRST", 1: "SECOND", 2: "THIRD"}


def test_run_memory_bounded_limits_parallel_peak_memory_and_returns_worker_errors():
    """Admitting a pair over budget or raising one worker error would break batch isolation."""
    from hydroseason._batch_scheduler import run_memory_bounded

    active_peak_gb = 0.0
    largest_active_peak_gb = 0.0
    lock = Lock()

    def worker(payload):
        nonlocal active_peak_gb, largest_active_peak_gb
        peak_gb, result = payload
        with lock:
            active_peak_gb += peak_gb
            largest_active_peak_gb = max(largest_active_peak_gb, active_peak_gb)
        try:
            if isinstance(result, Exception):
                raise result
            return result
        finally:
            with lock:
                active_peak_gb -= peak_gb

    items = [
        _item(0, 0.4, (0.4, "first")),
        _item(1, 0.7, (0.7, ValueError("broken"))),
        _item(2, 0.3, (0.3, "third")),
    ]

    results = run_memory_bounded(items, worker, max_workers=2, memory_budget_gb=1.0)

    assert largest_active_peak_gb <= 1.0
    assert results[0] == "first"
    assert results[2] == "third"
    assert isinstance(results[1], ValueError)


def test_run_memory_bounded_warns_once_for_all_oversized_items():
    """One warning per item would make a large batch noisy and hide the full scope."""
    from hydroseason._batch_scheduler import run_memory_bounded

    items = [_item(4, 1.2), _item(2, 1.1), _item(0, 0.4)]

    with pytest.warns(UserWarning) as caught:
        results = run_memory_bounded(items, lambda payload: payload, max_workers=2, memory_budget_gb=1.0)

    assert len(caught) == 1
    message = str(caught[0].message)
    assert "2" in message and "4" in message and "1.0" in message
    assert results == {4: 4, 2: 2, 0: 0}


def test_run_memory_bounded_propagates_keyboard_interrupt():
    """Catching BaseException would make cancellation and interactive shutdown unreliable."""
    from hydroseason._batch_scheduler import run_memory_bounded

    with pytest.raises(KeyboardInterrupt):
        run_memory_bounded(
            [_item(0, 0.2, "stop")],
            lambda _payload: (_ for _ in ()).throw(KeyboardInterrupt()),
            max_workers=1,
            memory_budget_gb=1.0,
        )
