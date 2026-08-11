"""Step progress for the public orchestrator.

``run_hydroseason`` can run for hours on a DEA fetch and, until now, printed
nothing at all: a notebook or terminal showed a live cell with no indication
of which phase was running or how far through it was. This module supplies
the STEP layer -- five coarse phases with start/finish lines and elapsed
times -- and deliberately does not reimplement the fine-grained bar. The
per-calendar-year tqdm bar inside
:func:`hydroseason._io_extent_cache.load_wofs_monthly_extent` already exists
and already ticks once per year (cache hits included); step 1 simply turns it
on and hands it a matching description.

Three reporter shapes, chosen by ``progress=``:

* ``False``/``None`` -- report nothing. The pre-0.1.1 behavior, still the
  default, so no existing caller's output changes.
* ``True`` -- write plain numbered lines to ``sys.stderr`` and let the
  per-year tqdm bar draw. Lines, not a redrawn step bar: stderr is routinely
  redirected to a log file for long runs (the whole point of the CLI), and a
  carriage-return bar renders as unreadable garbage there, while a five-line
  step log stays greppable.
* a callable -- receive :class:`ProgressEvent` objects and render them
  however the caller wants. The per-year tqdm bar is left OFF in this case:
  a caller collecting structured events is usually writing them to a file or
  a UI, and tqdm's control characters would interleave with them.

Imports stay pandas-free and numpy-free: this module must import in a
core-only install.
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from typing import Callable, Literal, Protocol, Sequence, runtime_checkable

ProgressPhase = Literal["start", "finish"]

# The five phases of run_hydroseason, in execution order. Fixed length: a run
# that skips rainfall still reports steps 3 and 4 (as "skipped") rather than
# renumbering the remaining ones, so "[5/5]" always means the report.
WORKFLOW_STEPS: tuple[str, ...] = (
    "resolve water input",
    "analyze catchment",
    "rainfall",
    "rainfall comparison",
    "write report",
)


@dataclass(frozen=True)
class ProgressEvent:
    """One step boundary crossed.

    ``elapsed_s`` is populated on ``"finish"`` when the matching ``"start"``
    was seen, and is ``None`` otherwise (a step reported only as finished --
    e.g. a skipped rainfall phase -- has no meaningful duration).
    """

    step: int
    total_steps: int
    label: str
    phase: ProgressPhase
    detail: str | None = None
    elapsed_s: float | None = None


@runtime_checkable
class ProgressReporter(Protocol):
    """Something that consumes :class:`ProgressEvent` objects.

    ``renders_subprogress`` tells :func:`hydroseason.workflow.run_hydroseason`
    whether it may also switch on the per-calendar-year tqdm bar underneath
    step 1.
    """

    renders_subprogress: bool

    def __call__(self, event: ProgressEvent) -> None: ...


class _NullReporter:
    renders_subprogress = False

    def __call__(self, event: ProgressEvent) -> None:
        return None


class _CallbackReporter:
    renders_subprogress = False

    def __init__(self, callback: Callable[[ProgressEvent], None]) -> None:
        self._callback = callback

    def __call__(self, event: ProgressEvent) -> None:
        self._callback(event)


class _StreamReporter:
    renders_subprogress = True

    def __init__(self, stream=None) -> None:
        # Resolved at call time, not construction time, when no stream was
        # given: notebook kernels replace sys.stderr after import.
        self._stream = stream

    def __call__(self, event: ProgressEvent) -> None:
        prefix = f"[{event.step}/{event.total_steps}] {event.label}"
        if event.phase == "start":
            suffix = f" ... {event.detail}" if event.detail else " ..."
            line = f"{prefix}{suffix}"
        else:
            line = f"{prefix} done"
            if event.detail:
                line += f" ({event.detail})"
            if event.elapsed_s is not None:
                line += f" in {event.elapsed_s:.1f}s"
        stream = self._stream if self._stream is not None else sys.stderr
        print(line, file=stream, flush=True)


def resolve_progress_reporter(progress, *, stream=None) -> ProgressReporter:
    """Turn a public ``progress=`` value into a reporter.

    ``stream`` is a test seam for the built-in renderer and is ignored for
    every other value of ``progress``.
    """
    if progress is None or progress is False:
        return _NullReporter()
    if progress is True:
        return _StreamReporter(stream)
    if callable(progress):
        return _CallbackReporter(progress)
    raise TypeError(
        "progress must be a bool or a callable taking a ProgressEvent; "
        f"got {type(progress).__name__}."
    )


class WorkflowProgress:
    """Emits step events for a fixed, 1-based sequence of phase labels."""

    def __init__(
        self,
        reporter: ProgressReporter,
        steps: Sequence[str] = WORKFLOW_STEPS,
    ) -> None:
        self._reporter = reporter
        self._steps = tuple(steps)
        self._started: dict[int, float] = {}

    @property
    def renders_subprogress(self) -> bool:
        return bool(getattr(self._reporter, "renders_subprogress", False))

    def label(self, index: int) -> str:
        return self._steps[index - 1]

    def subprogress_desc(self, index: int) -> str:
        """A description for a nested bar, prefixed so it lines up visually."""
        return f"[{index}/{len(self._steps)}] {self.label(index)}"

    def start(self, index: int, detail: str | None = None) -> None:
        self._started[index] = time.monotonic()
        self._reporter(
            ProgressEvent(
                step=index,
                total_steps=len(self._steps),
                label=self.label(index),
                phase="start",
                detail=detail,
            )
        )

    def finish(self, index: int, detail: str | None = None) -> None:
        started = self._started.pop(index, None)
        self._reporter(
            ProgressEvent(
                step=index,
                total_steps=len(self._steps),
                label=self.label(index),
                phase="finish",
                detail=detail,
                elapsed_s=None if started is None else time.monotonic() - started,
            )
        )


__all__ = [
    "ProgressEvent",
    "ProgressPhase",
    "ProgressReporter",
    "WORKFLOW_STEPS",
    "WorkflowProgress",
    "resolve_progress_reporter",
]
