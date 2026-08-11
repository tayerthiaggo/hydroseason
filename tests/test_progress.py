import io

import pytest

from hydroseason._progress import (
    WORKFLOW_STEPS,
    ProgressEvent,
    WorkflowProgress,
    resolve_progress_reporter,
)


def test_workflow_steps_are_the_five_orchestrator_phases():
    assert WORKFLOW_STEPS == (
        "resolve water input",
        "analyze catchment",
        "rainfall",
        "rainfall comparison",
        "write report",
    )


def test_progress_false_and_none_report_nothing():
    for value in (False, None):
        stream = io.StringIO()
        reporter = resolve_progress_reporter(value)
        tracker = WorkflowProgress(reporter)
        tracker.start(1)
        tracker.finish(1)
        assert stream.getvalue() == ""
        assert reporter.renders_subprogress is False


def test_progress_true_writes_numbered_step_lines_to_stderr():
    stream = io.StringIO()
    reporter = resolve_progress_reporter(True, stream=stream)
    tracker = WorkflowProgress(reporter)

    tracker.start(1, detail="fetching DEA WOfS")
    tracker.finish(1, detail="252 months")

    lines = stream.getvalue().splitlines()
    assert lines[0] == "[1/5] resolve water input ... fetching DEA WOfS"
    assert lines[1].startswith("[1/5] resolve water input done (252 months)")


def test_progress_callable_receives_structured_events():
    seen = []
    tracker = WorkflowProgress(resolve_progress_reporter(seen.append))

    tracker.start(2)
    tracker.finish(2, detail="seasonal")

    assert [(e.step, e.total_steps, e.label, e.phase) for e in seen] == [
        (2, 5, "analyze catchment", "start"),
        (2, 5, "analyze catchment", "finish"),
    ]
    assert seen[1].detail == "seasonal"
    assert seen[1].elapsed_s is not None and seen[1].elapsed_s >= 0.0


def test_callable_reporter_does_not_render_a_sub_progress_bar():
    """A caller who supplied a callable wants structured events, e.g. for a
    log file. Letting the DEA per-year tqdm bar also draw would interleave
    control characters into that log."""
    reporter = resolve_progress_reporter(lambda event: None)

    assert reporter.renders_subprogress is False


def test_builtin_reporter_renders_the_sub_progress_bar():
    assert resolve_progress_reporter(True).renders_subprogress is True


def test_subprogress_desc_is_prefixed_with_the_step_number():
    tracker = WorkflowProgress(resolve_progress_reporter(True))

    assert tracker.subprogress_desc(1) == "[1/5] resolve water input"


def test_finish_without_start_still_reports_and_omits_elapsed():
    seen = []
    WorkflowProgress(resolve_progress_reporter(seen.append)).finish(3, detail="skipped")

    assert seen[0].phase == "finish"
    assert seen[0].elapsed_s is None


def test_unknown_progress_value_is_rejected():
    with pytest.raises(TypeError, match="bool or a callable"):
        resolve_progress_reporter("yes")


def test_progress_event_is_immutable():
    event = ProgressEvent(1, 5, "resolve water input", "start", None, None)

    with pytest.raises(Exception):
        event.step = 2
