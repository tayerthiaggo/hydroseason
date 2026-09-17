import subprocess
from pathlib import Path

FORBIDDEN_TRACKED_PREFIXES = (
    "docs/paper/",
    "docs/audits/",
    "docs/superpowers/",
    "case_studies/results/",
    "case_studies/timing-identifiability/",
    "case_studies/trough-refinement/",
    "case_studies/recurrence-identifiability/",
)

FORBIDDEN_CAMPAIGN_SCRIPTS = (
    "scripts/audit_recurrence_impact.py",
    "scripts/build_final_review.py",
    "scripts/build_real_extent_fixture.py",
    "scripts/build_recurrence_identifiability_cohort.py",
    "scripts/build_timing_identifiability_cohort.py",
    "scripts/build_trough_refinement_cohort.py",
    "scripts/check_motivating_records.py",
    "scripts/compare_catchment_resolution_windows.py",
    "scripts/compare_resolution_signal_fidelity.py",
    "scripts/compare_wofs_resampling.py",
    "scripts/evaluate_final_pipeline.py",
    "scripts/evaluate_recurrence_identifiability_cohort.py",
    "scripts/evaluate_timing_identifiability_cohort.py",
    "scripts/evaluate_timing_recurrence.py",
    "scripts/evaluate_trough_refinement_cohort.py",
)


def test_release_repository_contains_no_paper_or_campaign_paths():
    result = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, check=True
    )
    tracked = [l.replace("\\\\", "/") for l in result.stdout.splitlines()]
    offenders = [p for p in tracked if p.startswith(FORBIDDEN_TRACKED_PREFIXES)]
    assert offenders == [], f"Forbidden tracked paths found: {offenders}"

    campaign_offenders = [p for p in tracked if p in FORBIDDEN_CAMPAIGN_SCRIPTS]
    assert campaign_offenders == [], f"Forbidden campaign scripts found: {campaign_offenders}"
