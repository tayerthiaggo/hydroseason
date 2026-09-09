"""Build the final scientific-hardening review bundle.

Captures the actual current-behaviour ("before") and corrected-candidate
("after") pipeline outputs for the five frozen real catchments, plus
deterministic smoke-case reports, into one offline-reviewable bundle. See
``docs/superpowers/plans/2026-09-08-final-scientific-hardening.md``.

Usage::

    .venv/Scripts/python.exe scripts/build_final_review.py --stage before --output-dir DIR
    .venv/Scripts/python.exe scripts/build_final_review.py --stage after --output-dir DIR
    .venv/Scripts/python.exe scripts/build_final_review.py --stage finalize --output-dir DIR

``before`` freezes the actual pre-change behaviour and refuses to overwrite
an existing baseline unless the five input hashes still match it (baseline
reuse must be provably identical inputs, not merely "the same output-dir
name"). ``after`` always regenerates. ``finalize`` reads the JUnit XML from
the repository's test run and rebuilds ``validation/test-results.html`` plus
the bundle index.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import html
import json
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import hydroseason  # noqa: E402
from hydroseason._catchment import analyze_catchment  # noqa: E402
from hydroseason._report_export import (  # noqa: E402
    build_events_export,
    build_hydro_years_export,
    build_monthly_export,
)
from hydroseason._trough_refinement import TroughRefinementPolicy  # noqa: E402
from hydroseason.report import generate_catchment_report  # noqa: E402
from scripts.evaluate_final_pipeline import compare_cycle_tables  # noqa: E402

DATA_ROOT = REPO_ROOT / "case_studies" / "data"

# Order matches the plan's frozen-inputs table; this is the full set of
# catchments any review bundle stage iterates over.
REVIEW_CATCHMENTS: tuple[str, ...] = (
    "daly_river_nt",
    "fitzroy_river_wa",
    "gilbert_river_qld",
    "lachlan_river_nsw",
    "moonie_river_qld_nsw",
)

# Fixed refinement tuple (plan global constraint): no grid search or
# retuning in this pass. The version label differs between "current" (the
# pre-Task-2/3 candidate, used only to label the already-frozen `before`
# baseline capture) and "corrected" (the candidate this pass produces), so a
# reader of the bundle cannot mistake a pre-fix baseline number for a
# post-fix candidate number. Both are pinned explicitly -- neither relies on
# TroughRefinementPolicy.version's dataclass default, which now tracks
# whatever the current source actually is.
_FIXED_TUPLE = {"huber_k": 1.345, "profile_loss_cutoff": 0.05, "pulse_z": 1.5}
CURRENT_CANDIDATE_POLICY = TroughRefinementPolicy(
    **_FIXED_TUPLE, version="trough_refinement_candidate_0_1"
)
CORRECTED_CANDIDATE_POLICY = TroughRefinementPolicy(
    **_FIXED_TUPLE, version="trough_refinement_candidate_0_2"
)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    import os

    os.close(descriptor)
    tmp_path = Path(tmp_name)
    try:
        tmp_path.write_text(
            json.dumps(payload, indent=2, default=_json_default, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(path)
    finally:
        tmp_path.unlink(missing_ok=True)


def _json_default(value: object) -> object:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return str(value)


def load_review_inputs(data_root: Path) -> dict[str, pd.DataFrame]:
    """Load and hash-verify the five frozen real catchment inputs.

    Verifies each file's SHA-256 against ``manifest.json`` *before* parsing
    it, and refuses (raises) on a missing entry or a hash mismatch -- a
    changed or substituted input must never be silently analysed as if it
    were the frozen record.
    """
    data_root = Path(data_root)
    manifest = json.loads((data_root / "manifest.json").read_text(encoding="utf-8"))
    frames: dict[str, pd.DataFrame] = {}
    for key in REVIEW_CATCHMENTS:
        entry_key = f"{key}_30m"
        entry = manifest["inputs"].get(entry_key)
        if entry is None:
            raise ValueError(f"manifest.json has no entry for {entry_key!r}")
        path = data_root / entry["file"]
        if not path.exists():
            raise FileNotFoundError(f"input file missing for {entry_key!r}: {path}")
        actual = _sha256_file(path)
        expected = entry["sha256"]
        if actual != expected:
            raise ValueError(
                f"SHA-256 mismatch for {path}: manifest says {expected}, file is {actual}"
            )
        frames[key] = pd.read_csv(path, index_col="date", parse_dates=True)
    return frames


def input_hashes(data_root: Path) -> dict[str, str]:
    data_root = Path(data_root)
    manifest = json.loads((data_root / "manifest.json").read_text(encoding="utf-8"))
    return {
        key: manifest["inputs"][f"{key}_30m"]["sha256"] for key in REVIEW_CATCHMENTS
    }


def run_cases(
    frames: dict[str, pd.DataFrame],
    *,
    output_dir: Path,
    refinement_policy: TroughRefinementPolicy | None,
) -> dict[str, dict[str, object]]:
    """Run each frame through the real routing pipeline and write its report.

    Reuses :func:`analyze_catchment` and :func:`generate_catchment_report`
    directly -- this is not a second route implementation. Writes the
    existing four compact CSVs (via ``generate_catchment_report``) plus the
    full rich export tables (hydro-years/monthly/events/low-spells) that the
    HTML report itself is built from, for later cycle/month diffing.
    """
    output_dir = Path(output_dir)
    results: dict[str, dict[str, object]] = {}
    for key, frame in frames.items():
        case_dir = output_dir / key
        try:
            analysis = analyze_catchment(frame, trough_refinement_policy=refinement_policy)
            paths = generate_catchment_report(frame, case_dir, name=key, analysis=analysis)
            full_hydro_years = build_hydro_years_export(analysis, name=key)
            full_monthly = build_monthly_export(frame, analysis=analysis, rainfall=None)
            full_events, full_low_spells = build_events_export(analysis)

            case_dir.mkdir(parents=True, exist_ok=True)
            full_table_paths = {
                "hydro_years": case_dir / "full_hydro_years.csv",
                "monthly": case_dir / "full_monthly.csv",
                "events": case_dir / "full_events.csv",
                "low_spells": case_dir / "full_low_spells.csv",
            }
            full_hydro_years.to_csv(full_table_paths["hydro_years"], index=False)
            full_monthly.to_csv(full_table_paths["monthly"], index=False)
            full_events.to_csv(full_table_paths["events"], index=False)
            full_low_spells.to_csv(full_table_paths["low_spells"], index=False)

            refinement_applicable = analysis.route == "per_year_detection"
            status = "ok"
            if refinement_policy is not None and not refinement_applicable:
                status = "not_run_for_event_route"

            config_values = (
                dataclasses.asdict(analysis.state.config) if analysis.state is not None else None
            )

            results[key] = {
                "status": status,
                "route": analysis.route,
                "route_reason": analysis.route_reason,
                "warnings": list(analysis.warnings),
                "refinement_applicable": refinement_applicable,
                "summary": analysis.summary_row(name=key),
                "config": config_values,
                "report_paths": {
                    # Relative to run_cases' own `output_dir` -- always
                    # well-defined, since `case_dir` is always
                    # `output_dir / key`. Callers that render links from a
                    # different location (e.g. the bundle root) prefix this
                    # with the known stage/variant path themselves; guessing
                    # that prefix in here broke when output_dir was passed
                    # as a relative path or nested at a different depth.
                    "html": paths.html.relative_to(output_dir.resolve()).as_posix()
                    if _is_relative_to(paths.html, output_dir.resolve())
                    else str(paths.html),
                    "monthly_csv": paths.monthly_csv.name,
                    "hydro_years_csv": paths.hydro_years_csv.name,
                    "wet_event_csv": paths.wet_event_csv.name,
                    "low_spells_csv": paths.low_spells_csv.name,
                },
                "full_table_paths": {
                    name: path.name for name, path in full_table_paths.items()
                },
                "hydro_years": full_hydro_years,
                "monthly": full_monthly,
                "events": full_events,
                "low_spells": full_low_spells,
            }
        except Exception as exc:  # noqa: BLE001 -- a failed case must not abort the run
            results[key] = {"status": "failed", "error": repr(exc)}
    return results


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def make_smoke_frames() -> dict[str, pd.DataFrame]:
    """Build the nine deterministic 15-year synthetic smoke cases.

    Count-free CSV-mode cases (no n_water/n_valid/n_aoi columns): they
    intentionally exercise the no-pixel-support path. Real catchments
    provide count metadata; these do not, on purpose.
    """
    index = pd.date_range("2005-01-01", periods=180, freq="MS")
    base = pd.DataFrame(
        {
            "extent_pct": np.tile([60, 80, 60, 35, 15, 8, 2, 2, 2, 8, 20, 40], 15),
            "invalid_pct": 0.0,
        },
        index=index,
    )
    cases = {
        name: base.copy()
        for name in (
            "clean-seasonal", "all-zero", "constant-water", "two-pulses",
            "long-plateau", "gap-at-low", "gap-at-recovery", "low-quality",
            "late-trough-short-following",
        )
    }
    cases["all-zero"]["extent_pct"] = 0.0
    cases["constant-water"]["extent_pct"] = 10.0
    cases["two-pulses"].loc["2012-05-01":"2012-09-01", "extent_pct"] = [8, 35, 7, 25, 6]
    cases["long-plateau"].loc["2012-06-01":"2012-10-01", "extent_pct"] = 2.0
    cases["gap-at-low"].loc["2012-08-01", ["extent_pct", "invalid_pct"]] = [np.nan, 100]
    cases["gap-at-recovery"].loc["2012-10-01", ["extent_pct", "invalid_pct"]] = [np.nan, 100]
    cases["low-quality"].loc["2012-09-01":"2012-11-01", "invalid_pct"] = 60.0
    cases["late-trough-short-following"].loc["2012-07-01":"2012-12-01", "extent_pct"] = [
        8, 6, 4, 3, 2, 1,
    ]
    cases["late-trough-short-following"].loc[
        "2013-04-01":"2013-07-01", ["extent_pct", "invalid_pct"]
    ] = [np.nan, 100]
    for frame in cases.values():
        frame["extent_pct"] = frame["extent_pct"].clip(lower=0, upper=100)
    return cases


def run_smoke_cases(
    output_dir: Path, *, policy: TroughRefinementPolicy
) -> dict[str, dict[str, object]]:
    """Run all nine smoke frames with the candidate enabled and write reports.

    Reuses the same ``run_cases``/``analyze_catchment``/
    ``generate_catchment_report`` path as the real catchments -- this is not
    a second detection or reporting implementation.
    """
    frames = make_smoke_frames()
    results = run_cases(frames, output_dir=output_dir, refinement_policy=policy)

    for key, case in results.items():
        if case.get("status") == "failed":
            continue
        route = case.get("route")
        hydro_years = case.get("hydro_years")
        if key in {"all-zero", "constant-water"} and route == "per_year_detection":
            case["smoke_check"] = "flat_record_should_not_publish_hydrological_years"
        elif route == "event_characterisation" and (hydro_years is None or hydro_years.empty):
            events = case.get("events")
            low_spells = case.get("low_spells")
            has_event_content = bool(
                (events is not None and not events.empty)
                or (low_spells is not None and not low_spells.empty)
            )
            case["smoke_check"] = "ok" if has_event_content else "event_route_has_no_events_or_low_spells"
        else:
            case["smoke_check"] = "ok"
    return results


def run_audit_probes() -> dict | None:
    """Run the audit's independent numerical probes and parse their JSON.

    Returns ``None`` (not an exception) if the probe script or its scipy
    dependency is unavailable -- the smoke index renders without this
    section rather than failing the whole bundle build over an optional
    component-level cross-check.
    """
    probe_path = REPO_ROOT / "docs" / "audits" / "2026-09-08-audit-probes.py"
    if not probe_path.exists():
        return None
    try:
        result = subprocess.run(
            [sys.executable, str(probe_path)],
            capture_output=True, text=True, check=True, cwd=REPO_ROOT,
        )
        return json.loads(result.stdout)
    except Exception:  # noqa: BLE001 -- optional cross-check, never fails the build
        return None


def build_smoke_index(
    output_dir: Path,
    results: dict[str, dict[str, object]],
    *,
    probe_output: dict | None = None,
) -> Path:
    """Write ``smoke/index.html`` linking all nine cases and their status."""
    rows = []
    for key in sorted(results):
        case = results[key]
        rows.append(
            f"<tr><td>{html.escape(key)}</td><td>{html.escape(str(case.get('status')))}</td>"
            f"<td>{html.escape(str(case.get('route')))}</td>"
            f"<td>{html.escape(str(case.get('smoke_check', '')))}</td><td>{_case_link(case)}</td></tr>"
        )

    probe_section = ""
    if probe_output:
        zero_scale = probe_output.get("zero_scale_profile", [])
        zero_scale_rows = "".join(
            f"<tr><td>{entry.get('factor')}</td><td>{entry.get('local_scale_pp')}</td>"
            f"<td>{html.escape(str(entry.get('status')))}</td>"
            f"<td>{html.escape(str(entry.get('boundary_candidates')))}</td></tr>"
            for entry in zero_scale
        )
        gap = probe_output.get("dropped_month_scenario", {})
        probe_section = (
            "<h2>Audit component probes (seven-month spans, not full records)</h2>"
            "<p>Reproductions from docs/audits/2026-09-08-scientific-audit.md, run via "
            "docs/audits/2026-09-08-audit-probes.py. These test refine_trough_span directly on a "
            "seven-month peak-to-peak span; they do NOT pass the public record-length gate and are "
            "not standalone catchment reports.</p>"
            "<table><tr><th>data scale factor</th><th>local_scale_pp</th><th>status</th>"
            "<th>boundary_candidates</th></tr>" + zero_scale_rows + "</table>"
            "<p>Dropped-month scenario (a genuinely missing month must not be silently treated as "
            f"observed): status=<strong>{html.escape(str(gap.get('status')))}</strong>, "
            f"recovery_start_present=<strong>{html.escape(str(gap.get('recovery_start_present')))}</strong>"
            "</p>"
        )

    text = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>Smoke cases</title></head><body>"
        "<h1>Deterministic smoke cases</h1>"
        "<p>Nine synthetic 15-year cases, refinement candidate enabled. "
        "Count-free CSV-mode cases exercise the no-pixel-support path.</p>"
        "<table><tr><th>case</th><th>status</th><th>route</th>"
        "<th>check</th><th>report</th></tr>" + "".join(rows) + "</table>"
        + probe_section
        + "</body></html>"
    )
    path = output_dir / "smoke" / "index.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def compare_monthly_tables(before: pd.DataFrame, after: pd.DataFrame) -> pd.DataFrame:
    """Outer-join two monthly export tables on ``date`` with NaN-aware equality.

    Unlike ``compare_cycle_tables`` (per hy_year), this pairs by calendar
    month; a month present in only one table is listed explicitly rather
    than silently dropped by an inner join.
    """
    if "date" not in before.columns or "date" not in after.columns:
        return pd.DataFrame()
    before = before.copy()
    after = after.copy()
    for frame in (before, after):
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    merged = before.merge(after, on="date", how="outer", suffixes=("_before", "_after"), indicator=True)
    return merged.sort_values("date").reset_index(drop=True)


def build_comparisons(output_dir: Path, catchments: list[str]) -> dict[str, object]:
    """Build the three-way comparison matrix for the five real catchments.

    Compares old default vs new default (regression control), old
    refinement vs corrected refinement, and current default vs corrected
    refinement -- never only against previously stored case-study HTML,
    which may use a different policy.
    """
    output_dir = Path(output_dir)
    comparisons_dir = output_dir / "comparisons"
    comparisons_dir.mkdir(parents=True, exist_ok=True)

    pairs = {
        "old_default_vs_new_default": ("before/default", "after/default"),
        "old_refinement_vs_corrected_refinement": ("before/refinement", "after/refinement"),
        "current_default_vs_corrected_refinement": ("after/default", "after/refinement"),
    }

    catchment_rows: list[dict[str, object]] = []
    cycle_frames: list[pd.DataFrame] = []
    month_frames: list[pd.DataFrame] = []

    for catchment in catchments:
        for comparison_name, (before_variant, after_variant) in pairs.items():
            before_dir = output_dir / before_variant / catchment
            after_dir = output_dir / after_variant / catchment
            before_hy_path = before_dir / "full_hydro_years.csv"
            after_hy_path = after_dir / "full_hydro_years.csv"
            before_monthly_path = before_dir / "full_monthly.csv"
            after_monthly_path = after_dir / "full_monthly.csv"

            row: dict[str, object] = {"catchment": catchment, "comparison": comparison_name}
            if before_hy_path.exists() and after_hy_path.exists():
                before_hy = pd.read_csv(before_hy_path)
                after_hy = pd.read_csv(after_hy_path)
                if "hy_year" in before_hy.columns and "hy_year" in after_hy.columns:
                    cycle_diff, counts = compare_cycle_tables(before_hy, after_hy)
                    cycle_diff.insert(0, "comparison", comparison_name)
                    cycle_diff.insert(0, "catchment", catchment)
                    cycle_frames.append(cycle_diff)
                    row.update({f"cycles_{key}": value for key, value in counts.items()})
                else:
                    row["cycles_note"] = "no hy_year column (event route or empty)"
            else:
                row["cycles_note"] = "missing input table"

            if before_monthly_path.exists() and after_monthly_path.exists():
                before_month = pd.read_csv(before_monthly_path)
                after_month = pd.read_csv(after_monthly_path)
                month_diff = compare_monthly_tables(before_month, after_month)
                if not month_diff.empty:
                    month_diff.insert(0, "comparison", comparison_name)
                    month_diff.insert(0, "catchment", catchment)
                    month_frames.append(month_diff)
                row["months_compared"] = len(month_diff)

            catchment_rows.append(row)

    catchments_csv = pd.DataFrame(catchment_rows)
    cycles_csv = (
        pd.concat(cycle_frames, ignore_index=True) if cycle_frames else pd.DataFrame()
    )
    months_csv = (
        pd.concat(month_frames, ignore_index=True) if month_frames else pd.DataFrame()
    )
    catchments_csv.to_csv(comparisons_dir / "catchments.csv", index=False)
    cycles_csv.to_csv(comparisons_dir / "cycles.csv", index=False)
    months_csv.to_csv(comparisons_dir / "months.csv", index=False)
    return {
        "catchments_rows": len(catchments_csv),
        "cycles_rows": len(cycles_csv),
        "months_rows": len(months_csv),
    }


def write_review_notes(output_dir: Path, catchments: list[str]) -> Path:
    """Write ``review-notes.md``: one row per catchment, blank for the user's response."""
    lines = [
        "# Review notes",
        "",
        "Development review; not blinded validation. One row per catchment; fill in the",
        "blank columns while inspecting the linked reports and diffs.",
        "",
        "Inspection prompts: wet season split correctly? Recovery allocated too early or",
        "too late? A pulse incorrectly treated as a new year? Unsupported precision claimed?",
        "Any surprising route or condition change versus the frozen `before/` baseline?",
        "",
        "| Catchment | Year/date | Issue seen | Expected behaviour | Screenshot/report reference |",
        "|---|---|---|---|---|",
    ]
    for catchment in catchments:
        lines.append(f"| {catchment} | | | | |")
    text = "\n".join(lines) + "\n"
    path = output_dir / "review-notes.md"
    path.write_text(text, encoding="utf-8")
    return path


def _case_link(case: dict, prefix: str = "") -> str:
    """Build an href to a case's report, relative to the linking page.

    ``report_paths["html"]`` is relative to that case's own run_cases
    ``output_dir`` (e.g. ``daly_river_nt/daly-river-nt.html``); ``prefix``
    supplies the path from the linking page down to that same output_dir
    (e.g. ``"after/refinement/"``), which differs by section.
    """
    report = case.get("report_paths", {}).get("html") if case.get("status") != "failed" else None
    if not report:
        return "(no report)"
    # An already-frozen manifest (e.g. the immutable `before/` baseline,
    # captured before this path scheme existed) may still carry an absolute
    # path from an older run_cases version. Never touch that frozen
    # manifest to "fix" it -- render it as a working `file://` URI instead
    # of prepending a prefix onto an already-absolute path.
    if Path(report).is_absolute():
        href = Path(report).as_uri()
    else:
        href = f"{prefix}{report}"
    return f'<a href="{html.escape(href)}">{html.escape(href)}</a>'


def build_index(output_dir: Path) -> Path:
    """Build/rebuild the bundle's offline ``index.html``.

    Links the five primary candidate reports, the frozen baseline, the
    smoke cases, the comparison CSVs, the test summary, the reviews, and
    the manifest. Uses "unchanged" for controls -- never manufactured
    positive-improvement language.
    """
    output_dir = Path(output_dir)
    before_manifest_path = output_dir / "before" / "manifest.json"
    after_manifest_path = output_dir / "after" / "manifest.json"
    sections: list[str] = []

    policy_note = ""
    after_manifest: dict | None = None
    if after_manifest_path.exists():
        after_manifest = json.loads(after_manifest_path.read_text(encoding="utf-8"))
        policy = after_manifest.get("policies", {}).get("refinement", {})
        policy_note = (
            f"<p><strong>Candidate policy:</strong> huber_k={policy.get('huber_k')}, "
            f"profile_loss_cutoff={policy.get('profile_loss_cutoff')}, "
            f"pulse_z={policy.get('pulse_z')}, version={html.escape(str(policy.get('version')))}. "
            "<strong>Development review; not blinded validation.</strong></p>"
        )

    test_results_path = output_dir / "validation" / "test-results.html"
    if test_results_path.exists():
        test_results_text = test_results_path.read_text(encoding="utf-8")
        status_match = re.search(r"Software test status:\s*<strong>([^<]+)</strong>", test_results_text)
        status = status_match.group(1) if status_match else "unknown"
        policy_note += (
            f'<p><strong>Software test status:</strong> {html.escape(status)} '
            '(<a href="validation/test-results.html">details</a>)</p>'
        )

    if after_manifest is not None:
        catchments_csv_path = output_dir / "comparisons" / "catchments.csv"
        by_catchment: dict[str, dict] = {}
        if catchments_csv_path.exists():
            comparisons = pd.read_csv(catchments_csv_path)
            current_vs_corrected = comparisons.loc[
                comparisons["comparison"] == "current_default_vs_corrected_refinement"
            ]
            by_catchment = {
                str(row["catchment"]): row.to_dict()
                for _, row in current_vs_corrected.iterrows()
            }
        primary_rows = []
        for key in REVIEW_CATCHMENTS:
            default_case = after_manifest.get("cases", {}).get("default", {}).get(key, {})
            refinement_case = after_manifest.get("cases", {}).get("refinement", {}).get(key, {})
            default_route = default_case.get("route", "")
            refinement_route = refinement_case.get("route", "")
            route_cell = (
                "unchanged" if default_route == refinement_route
                else f"{html.escape(str(default_route))} -&gt; {html.escape(str(refinement_route))}"
            )
            comparison = by_catchment.get(key, {})
            boundary_shifted = comparison.get("cycles_boundary_shifted", "n/a")
            newly_uncomputable = comparison.get("cycles_newly_uncomputable", "n/a")
            interval_width_changed = comparison.get("cycles_interval_width_changed", "n/a")
            widened = comparison.get("cycles_interval_widened", "n/a")
            narrowed = comparison.get("cycles_interval_narrowed", "n/a")
            width_cell = f"{interval_width_changed} ({widened} wider / {narrowed} narrower)"
            default_events = default_case.get("summary", {}).get("n_wet_events")
            refinement_events = refinement_case.get("summary", {}).get("n_wet_events")
            event_delta = (
                "unchanged" if default_events == refinement_events
                else f"{default_events} -&gt; {refinement_events}"
            )
            primary_rows.append(
                f"<tr><td>{html.escape(key)}</td><td>{route_cell}</td>"
                f"<td>{boundary_shifted}</td><td>{newly_uncomputable}</td>"
                f"<td>{width_cell}</td><td>{event_delta}</td>"
                f"<td>{_case_link(refinement_case, prefix='after/refinement/')}</td>"
                f"<td>{_case_link(default_case, prefix='after/default/')}</td></tr>"
            )
        sections.append(
            "<h2>Five primary candidate reports (current default vs corrected refinement)</h2>"
            "<p>lachlan_river_nsw and moonie_river_qld_nsw route to event_characterisation and publish no "
            "hydrological years, so their cycle-level counters below are vacuously zero; the substantive "
            "paired-cycle evidence is the three seasonal catchments plus the synthetic pipeline evaluation "
            "(see validation/pipeline.json).</p>"
            "<table><tr><th>catchment</th><th>route</th>"
            "<th>boundaries shifted</th><th>newly uncomputable</th>"
            "<th>interval width changed</th><th>wet events</th>"
            "<th>refinement report</th>"
            "<th>default report</th></tr>" + "".join(primary_rows) + "</table>"
        )

    for label, manifest_path in (("before", before_manifest_path), ("after", after_manifest_path)):
        if not manifest_path.exists():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        rows = []
        for variant in ("default", "refinement"):
            cases = manifest.get("cases", {}).get(variant, {})
            for key, case in cases.items():
                rows.append(
                    f"<tr><td>{html.escape(variant)}</td><td>{html.escape(key)}</td>"
                    f"<td>{html.escape(str(case.get('status')))}</td>"
                    f"<td>{html.escape(str(case.get('route')))}</td>"
                    f"<td>{_case_link(case, prefix=f'{label}/{variant}/')}</td></tr>"
                )
        sections.append(
            f"<h2>{html.escape(label)}</h2>"
            "<table><tr><th>variant</th><th>catchment</th><th>status</th>"
            "<th>route</th><th>report</th></tr>" + "".join(rows) + "</table>"
        )

    links: list[str] = []
    for label, rel_path in (
        ("Smoke cases", "smoke/index.html"),
        ("Review notes (fill in during inspection)", "review-notes.md"),
        ("Comparison: catchment summary", "comparisons/catchments.csv"),
        ("Comparison: per-cycle diff", "comparisons/cycles.csv"),
        ("Comparison: per-month diff", "comparisons/months.csv"),
        ("Test results", "validation/test-results.html"),
        ("Opus checkpoint 1 (math/validation)", "reviews/opus-math-validation.md"),
        ("Opus checkpoint 2 (final integration)", "reviews/opus-final.md"),
        ("Codex handoff", "handoff-for-codex.md"),
        ("Before manifest", "before/manifest.json"),
        ("After manifest", "after/manifest.json"),
        ("Bundle manifest", "manifest.json"),
    ):
        if (output_dir / rel_path).exists():
            links.append(f'<li><a href="{html.escape(rel_path)}">{html.escape(label)}</a></li>')
    links_html = f"<h2>Bundle links</h2><ul>{''.join(links)}</ul>" if links else ""

    text = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>Final scientific hardening review</title></head><body>"
        "<h1>Final scientific hardening review</h1>"
        + policy_note
        + links_html
        + "".join(sections)
        + "</body></html>"
    )
    index_path = output_dir / "index.html"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(text, encoding="utf-8")

    build_bundle_manifest(output_dir)
    return index_path


def build_bundle_manifest(output_dir: Path) -> Path:
    """Write the top-level bundle manifest: what stages/artifacts exist."""
    output_dir = Path(output_dir)

    def _load(rel_path: str) -> dict | None:
        path = output_dir / rel_path
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    before = _load("before/manifest.json")
    after = _load("after/manifest.json")
    manifest = {
        "bundle": "final-scientific-hardening-2026-09-08",
        # `build_bundle_manifest` runs on every stage, most often last as
        # part of `finalize` (after the test suite, possibly after further
        # edits) -- its live-tree read is a stamp of *that* moment, not
        # proof of what generated the before/after numbers. Each stage's
        # own manifest already captured its own source at generation time;
        # surface those explicitly instead of letting a reader conflate
        # this finalize-time stamp with them (C3, 2026-09-08 review).
        "finalize_time_source": _git_info(REPO_ROOT),
        "before_source": before.get("source") if before else None,
        "after_source": after.get("source") if after else None,
        "environment": _environment_info(),
        "stages_present": {
            "before": before is not None,
            "after": after is not None,
            "smoke": (output_dir / "smoke" / "index.html").exists(),
            "comparisons": (output_dir / "comparisons" / "catchments.csv").exists(),
            "validation": (output_dir / "validation" / "test-results.html").exists(),
        },
        "before_input_hashes": before.get("input_hashes") if before else None,
        "after_input_hashes": after.get("input_hashes") if after else None,
        "after_policy": after.get("policies", {}).get("refinement") if after else None,
    }
    _write_json_atomic(output_dir / "manifest.json", manifest)
    return output_dir / "manifest.json"


def _git_info(repo_root: Path) -> dict[str, object]:
    def _run(args: list[str]) -> str:
        return subprocess.run(
            args, cwd=repo_root, capture_output=True, text=True, check=True
        ).stdout.strip()

    revision = _run(["git", "rev-parse", "HEAD"])
    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    tracked_diff = subprocess.run(
        ["git", "diff", "HEAD"], cwd=repo_root, capture_output=True, text=True, check=True
    ).stdout
    status = _run(["git", "status", "--porcelain"])

    # `git diff HEAD` never touches untracked files, so a patch hash alone
    # cannot establish source identity for new files -- new evaluation
    # scripts and their tests included (C3, 2026-09-08 review). Archive the
    # actual content of every untracked *.py source file (not the untracked
    # generated-evidence directories, which are outputs, not source) so the
    # manifest carries a reproducible snapshot, not just a claim a hash
    # matches something nobody can inspect.
    untracked_python_sources: dict[str, str] = {}
    for line in status.splitlines():
        if not line.startswith("??"):
            continue
        rel_path = line[3:].strip().strip('"')
        if not rel_path.endswith(".py"):
            continue
        full_path = repo_root / rel_path
        if full_path.is_file():
            untracked_python_sources[rel_path] = full_path.read_text(encoding="utf-8")

    return {
        "revision": revision,
        "branch": branch,
        "dirty": bool(status.strip()),
        "dirty_patch_hash": (
            hashlib.sha256(tracked_diff.encode("utf-8")).hexdigest() if tracked_diff else None
        ),
        # The diff text itself, not only its hash: a hash cannot be
        # inspected or reapplied by a reader who does not already possess
        # the patch.
        "tracked_diff_patch": tracked_diff or None,
        "untracked_python_sources": untracked_python_sources,
        "untracked_python_source_hashes": {
            path: hashlib.sha256(text.encode("utf-8")).hexdigest()
            for path, text in untracked_python_sources.items()
        },
        "porcelain_status": status.splitlines(),
    }


def _environment_info() -> dict[str, str]:
    import scipy  # noqa: PLC0415 -- optional dependency, only used for this label

    return {
        "python": sys.version.split()[0],
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "scipy": scipy.__version__,
        "hydroseason": hydroseason.__version__,
    }


def _build_manifest(
    *,
    stage: str,
    hashes: dict[str, str],
    default_results: dict[str, dict[str, object]],
    refinement_results: dict[str, dict[str, object]],
    refinement_policy: TroughRefinementPolicy,
) -> dict[str, object]:
    def _strip_tables(results: dict[str, dict[str, object]]) -> dict[str, dict[str, object]]:
        return {
            key: {k: v for k, v in case.items() if k not in {"hydro_years", "monthly", "events", "low_spells"}}
            for key, case in results.items()
        }

    return {
        "stage": stage,
        "source": _git_info(REPO_ROOT),
        "environment": _environment_info(),
        "seed": 0,
        "input_hashes": hashes,
        "policies": {
            "default": None,
            "refinement": dataclasses.asdict(refinement_policy),
        },
        "cases": {
            "default": _strip_tables(default_results),
            "refinement": _strip_tables(refinement_results),
        },
    }


def _run_stage(stage: str, output_dir: Path) -> int:
    output_dir = Path(output_dir)
    stage_dir = output_dir / stage
    hashes = input_hashes(DATA_ROOT)

    if stage == "before":
        manifest_path = stage_dir / "manifest.json"
        if manifest_path.exists():
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
            if existing.get("input_hashes") == hashes:
                print(f"[build_final_review] existing baseline at {manifest_path} matches current inputs; leaving it untouched")
                return 0
            raise SystemExit(
                f"refusing to overwrite existing baseline at {manifest_path}: "
                "recorded input hashes do not match the current inputs"
            )
        policy = CURRENT_CANDIDATE_POLICY
    elif stage == "after":
        policy = CORRECTED_CANDIDATE_POLICY
    else:
        raise SystemExit(f"unknown stage for _run_stage: {stage!r}")

    frames = load_review_inputs(DATA_ROOT)
    default_results = run_cases(frames, output_dir=stage_dir / "default", refinement_policy=None)
    refinement_results = run_cases(frames, output_dir=stage_dir / "refinement", refinement_policy=policy)

    manifest = _build_manifest(
        stage=stage,
        hashes=hashes,
        default_results=default_results,
        refinement_results=refinement_results,
        refinement_policy=policy,
    )

    variant_results = {"default": default_results, "refinement": refinement_results}
    smoke_results: dict[str, dict[str, object]] = {}
    if stage == "after":
        smoke_results = run_smoke_cases(output_dir / "smoke", policy=policy)
        build_smoke_index(output_dir, smoke_results, probe_output=run_audit_probes())
        manifest["smoke"] = {
            key: {k: v for k, v in case.items() if k not in {"hydro_years", "monthly", "events", "low_spells"}}
            for key, case in smoke_results.items()
        }
        comparison_summary = build_comparisons(output_dir, list(REVIEW_CATCHMENTS))
        manifest["comparisons"] = comparison_summary
        write_review_notes(output_dir, list(REVIEW_CATCHMENTS))

    _write_json_atomic(stage_dir / "manifest.json", manifest)

    failed = [
        f"{variant}/{key}"
        for variant, results in variant_results.items()
        for key, case in results.items()
        if case.get("status") == "failed"
    ] + [f"smoke/{key}" for key, case in smoke_results.items() if case.get("status") == "failed"]
    if failed:
        print(f"[build_final_review] {stage}: failed cases: {failed}", file=sys.stderr)

    build_index(output_dir)
    return 1 if failed else 0


def _run_finalize(output_dir: Path) -> int:
    output_dir = Path(output_dir)
    junit_path = output_dir / "validation" / "pytest.xml"
    validation_dir = output_dir / "validation"
    validation_dir.mkdir(parents=True, exist_ok=True)
    result_html_path = validation_dir / "test-results.html"

    if not junit_path.exists():
        text = (
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<title>Test results</title></head><body>"
            f"<h1>Test results</h1><p>JUnit XML not found at {html.escape(str(junit_path))}: "
            "this is NOT a pass.</p></body></html>"
        )
        result_html_path.write_text(text, encoding="utf-8")
        build_index(output_dir)
        return 1

    try:
        tree = ET.parse(junit_path)
    except ET.ParseError as exc:
        text = (
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<title>Test results</title></head><body>"
            f"<h1>Test results</h1><p>JUnit XML at {html.escape(str(junit_path))} failed to "
            f"parse: {html.escape(str(exc))}. This is NOT a pass.</p></body></html>"
        )
        result_html_path.write_text(text, encoding="utf-8")
        build_index(output_dir)
        return 1

    root = tree.getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    total = sum(int(s.get("tests", 0)) for s in suites)
    failures = sum(int(s.get("failures", 0)) for s in suites)
    errors = sum(int(s.get("errors", 0)) for s in suites)
    skipped = sum(int(s.get("skipped", 0)) for s in suites)
    passed = total - failures - errors - skipped
    is_pass = total > 0 and failures == 0 and errors == 0

    failure_rows = []
    for suite in suites:
        for case in suite.findall("testcase"):
            for tag in ("failure", "error"):
                node = case.find(tag)
                if node is not None:
                    failure_rows.append(
                        f"<tr><td>{html.escape(case.get('classname', ''))}</td>"
                        f"<td>{html.escape(case.get('name', ''))}</td>"
                        f"<td>{html.escape(tag)}</td>"
                        f"<td><pre>{html.escape((node.get('message') or '')[:500])}</pre></td></tr>"
                    )

    text = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>Test results</title></head><body>"
        "<h1>Test results</h1>"
        f"<p>total={total} passed={passed} failures={failures} errors={errors} skipped={skipped}</p>"
        f"<p>Software test status: <strong>{'PASS' if is_pass else 'NOT A PASS'}</strong></p>"
        "<table><tr><th>class</th><th>test</th><th>kind</th><th>message</th></tr>"
        + "".join(failure_rows)
        + "</table></body></html>"
    )
    result_html_path.write_text(text, encoding="utf-8")
    build_index(output_dir)
    return 0 if is_pass else 1


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=["before", "after", "finalize"], required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main() -> int:
    args = _build_arg_parser().parse_args()
    if args.stage in {"before", "after"}:
        return _run_stage(args.stage, args.output_dir)
    return _run_finalize(args.output_dir)


if __name__ == "__main__":
    raise SystemExit(main())
