from __future__ import annotations

import os
import tempfile
from pathlib import Path

import nbformat
from nbclient import NotebookClient

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "notebooks/05_0_1_improvements.ipynb"


def main() -> int:
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    with tempfile.TemporaryDirectory(prefix="hydroseason-notebook-05-") as tmp:
        previous_output = os.environ.get("HYDROSEASON_NOTEBOOK_OUTPUT")
        previous_live = os.environ.get("HYDROSEASON_RUN_LIVE_DEA")
        os.environ["HYDROSEASON_NOTEBOOK_OUTPUT"] = tmp
        os.environ["HYDROSEASON_RUN_LIVE_DEA"] = "0"
        try:
            NotebookClient(
                notebook,
                timeout=240,
                kernel_name="python3",
                resources={"metadata": {"path": str(NOTEBOOK.parent)}},
            ).execute()
        finally:
            if previous_output is None:
                os.environ.pop("HYDROSEASON_NOTEBOOK_OUTPUT", None)
            else:
                os.environ["HYDROSEASON_NOTEBOOK_OUTPUT"] = previous_output
            if previous_live is None:
                os.environ.pop("HYDROSEASON_RUN_LIVE_DEA", None)
            else:
                os.environ["HYDROSEASON_RUN_LIVE_DEA"] = previous_live
    print(f"CHECK PASS: executed {NOTEBOOK.name} offline")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
