"""Generate the README/docs report preview image from live HTML report output."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import pandas as pd

from hydroseason import classify_rainfall, generate_html_report


ROOT = Path(__file__).resolve().parents[1]
INPUT_CSV = ROOT / "data" / "monthly_rainfall.csv"
REPORT_HTML = ROOT / "docs" / "examples" / "hydroseason_report.html"
OUTPUT_PNG = ROOT / "docs" / "assets" / "images" / "hydroseason-report-preview.png"

BROWSER_CANDIDATES = (
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
)

WRAPPER_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <style>
    html, body {{
      margin: 0;
      width: 1600px;
      height: 980px;
      overflow: hidden;
      background: linear-gradient(180deg, #f4f7fb 0%, #edf3f8 100%);
    }}
    body {{
      padding: 28px;
      box-sizing: border-box;
      font-family: Arial, sans-serif;
    }}
    .frame {{
      width: 1544px;
      height: 924px;
      overflow: hidden;
      border-radius: 14px;
      box-shadow: 0 18px 48px rgba(15, 23, 42, 0.12);
      background: white;
      border: 1px solid #d8e2ec;
    }}
    iframe {{
      width: 1544px;
      height: 1600px;
      border: 0;
      display: block;
    }}
  </style>
</head>
<body>
  <div class="frame">
    <iframe src="{report_uri}" title="HydroSeason report preview"></iframe>
  </div>
</body>
</html>
"""


def _find_browser() -> Path:
    for candidate in BROWSER_CANDIDATES:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "Could not find a local Edge/Chrome browser for headless preview capture."
    )


def _render_preview(report_path: Path, output_path: Path) -> None:
    browser = _find_browser()

    with tempfile.TemporaryDirectory(prefix="hydroseason-preview-", dir=ROOT / "output") as tmpdir:
        tmpdir_path = Path(tmpdir)
        wrapper_path = tmpdir_path / "report-preview-wrapper.html"
        profile_dir = tmpdir_path / "browser-profile"
        screenshot_path = tmpdir_path / "hydroseason-report-preview.png"

        profile_dir.mkdir()
        wrapper_path.write_text(
            WRAPPER_HTML.format(report_uri=report_path.resolve().as_uri()),
            encoding="utf-8",
        )

        cmd = [
            str(browser),
            "--headless",
            "--disable-gpu",
            "--hide-scrollbars",
            "--no-first-run",
            "--no-default-browser-check",
            f"--user-data-dir={profile_dir}",
            "--window-size=1600,980",
            "--virtual-time-budget=5000",
            "--run-all-compositor-stages-before-draw",
            f"--screenshot={screenshot_path}",
            "--allow-file-access-from-files",
            wrapper_path.resolve().as_uri(),
        ]
        subprocess.run(cmd, check=True)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(screenshot_path, output_path)


def main() -> None:
    raw = pd.read_csv(INPUT_CSV)
    artifacts = classify_rainfall(raw)

    REPORT_HTML.parent.mkdir(parents=True, exist_ok=True)
    generate_html_report(artifacts, REPORT_HTML)
    _render_preview(REPORT_HTML, OUTPUT_PNG)
    print(OUTPUT_PNG)


if __name__ == "__main__":
    main()
