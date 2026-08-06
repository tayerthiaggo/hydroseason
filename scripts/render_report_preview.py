"""Render a PNG preview of a HydroSeason self-contained HTML report.

Used to regenerate docs/assets/report-preview.png (the README/docs "what
you get" screenshot) whenever the report template changes. Requires the
``dev`` extra (``pip install -e ".[dev]"`` then ``playwright install
chromium``); never a runtime dependency of the package itself.
"""
from __future__ import annotations

import argparse
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def render_preview(
    html_path: Path,
    png_path: Path,
    *,
    width: int = 1440,
    device_scale_factor: int = 2,
    bottom_selector: str = "section.plot-primary",
    max_height: int = 2200,
) -> None:
    """Screenshot from the page top down through ``bottom_selector``'s
    bottom edge (title + KPIs + the primary timeline chart) -- the "hero"
    region, not the full multi-chart report. The viewport is grown to fit
    the whole clip region first: Playwright's ``clip`` does not auto-scroll
    or expand the capture beyond the current viewport.
    """
    from playwright.sync_api import sync_playwright

    html_path = html_path.resolve()
    png_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(
            viewport={"width": width, "height": max_height},
            device_scale_factor=device_scale_factor,
        )
        page.goto(html_path.as_uri())
        page.wait_for_load_state("networkidle")

        clip = {"x": 0, "y": 0, "width": width, "height": max_height}
        box = page.locator(bottom_selector).first.bounding_box()
        if box is not None:
            clip["height"] = min(box["y"] + box["height"], max_height)

        page.screenshot(path=str(png_path), clip=clip)
        browser.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "html_path", nargs="?",
        default=REPO_ROOT / "docs" / "examples" / "fitzroy-river-wa.html",
        type=Path,
    )
    parser.add_argument(
        "png_path", nargs="?",
        default=REPO_ROOT / "docs" / "assets" / "report-preview.png",
        type=Path,
    )
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--device-scale-factor", type=int, default=2)
    args = parser.parse_args()
    render_preview(
        args.html_path, args.png_path,
        width=args.width, device_scale_factor=args.device_scale_factor,
    )
    print(f"Wrote {args.png_path}")


if __name__ == "__main__":
    main()
