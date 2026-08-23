from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROTECTED_BASELINE = (
    REPO_ROOT / "tests" / "fixtures" / "scientific_baseline_0_1_1"
).resolve()


def refuse_protected_baseline_output(output_dir: Path) -> None:
    target = output_dir.resolve()
    if target == PROTECTED_BASELINE or PROTECTED_BASELINE in target.parents:
        raise ValueError(
            "artifact regeneration cannot overwrite the protected scientific baseline"
        )
