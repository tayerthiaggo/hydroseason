"""Generate the README/docs report preview image."""

from __future__ import annotations

from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import pandas as pd

from hydroseason import classify_rainfall


ROOT = Path(__file__).resolve().parents[1]
INPUT_CSV = ROOT / "data" / "monthly_rainfall.csv"
OUTPUT_PNG = ROOT / "docs" / "assets" / "images" / "hydroseason-report-preview.png"

WET = "#1565C0"
DRY = "#EF3800"
TEXT = "#263238"
GRID = "#ECEFF1"


def _season_colour(season: str) -> str:
    if season == "Wet":
        return WET
    if season == "Dry":
        return DRY
    return "#9E9E9E"


def main() -> None:
    raw = pd.read_csv(INPUT_CSV)
    artifacts = classify_rainfall(raw)
    result = artifacts.result.copy()
    result["Date"] = pd.to_datetime(result["Date"])

    annual = (
        result[["Hydro_Year", "wet_total", "dry_total", "Annual_SPI"]]
        .drop_duplicates("Hydro_Year")
        .sort_values("Hydro_Year")
    )
    climatology = (
        result.assign(Month=result["Date"].dt.month)
        .groupby("Month", as_index=False)["Rainfall_mm"]
        .mean()
    )

    fig = plt.figure(figsize=(13.5, 8), facecolor="white")
    gs = fig.add_gridspec(2, 2, height_ratios=[1.4, 1], hspace=0.32, wspace=0.18)
    ax_timeline = fig.add_subplot(gs[0, :])
    ax_clim = fig.add_subplot(gs[1, 0])
    ax_annual = fig.add_subplot(gs[1, 1])

    colours = [_season_colour(s) for s in result["SeasonType"].astype(str)]
    ax_timeline.bar(
        result["Date"],
        result["Rainfall_mm"],
        width=24,
        color=colours,
        edgecolor="white",
        linewidth=0.25,
    )
    ax_timeline.set_title(
        "HydroSeason example report: rainfall-derived Wet/Dry seasons",
        loc="left",
        fontsize=15,
        fontweight="bold",
        color=TEXT,
    )
    ax_timeline.set_ylabel("Monthly rainfall (mm)")
    ax_timeline.xaxis.set_major_locator(mdates.YearLocator(4))
    ax_timeline.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    month_names = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"]
    ax_clim.bar(
        climatology["Month"],
        climatology["Rainfall_mm"],
        color="#78909C",
        edgecolor="white",
    )
    ax_clim.set_title("Monthly climatology", loc="left", fontsize=12, fontweight="bold")
    ax_clim.set_ylabel("Mean rainfall (mm)")
    ax_clim.set_xticks(range(1, 13), month_names)

    ax_annual.bar(
        annual["Hydro_Year"],
        annual["wet_total"],
        color=WET,
        label="Wet total",
    )
    ax_annual.bar(
        annual["Hydro_Year"],
        annual["dry_total"],
        bottom=annual["wet_total"],
        color=DRY,
        label="Dry total",
    )
    ax_annual.set_title("Wet/Dry totals by hydrological year", loc="left", fontsize=12, fontweight="bold")
    ax_annual.set_ylabel("Rainfall (mm)")
    ax_annual.xaxis.set_major_locator(plt.MaxNLocator(8, integer=True))

    for ax in (ax_timeline, ax_clim, ax_annual):
        ax.grid(axis="y", color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        ax.spines[["top", "right"]].set_visible(False)
        ax.spines[["left", "bottom"]].set_color("#B0BEC5")
        ax.tick_params(colors="#546E7A")

    handles = [
        mpatches.Patch(color=WET, label="Wet"),
        mpatches.Patch(color=DRY, label="Dry"),
    ]
    ax_timeline.legend(handles=handles, frameon=False, ncol=2, loc="upper right")

    d = artifacts.diagnostics
    fig.text(
        0.02,
        0.02,
        (
            f"Full bundled monthly_rainfall.csv dataset: {result['Date'].min():%Y-%m} "
            f"to {result['Date'].max():%Y-%m}. Regime: {d.regime}; "
            f"Walsh-Lawler SI: {d.walsh_lawler_si:.3f}; STL F_S: {d.stl_strength:.3f}."
        ),
        fontsize=9,
        color="#546E7A",
    )

    OUTPUT_PNG.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUTPUT_PNG, dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(OUTPUT_PNG)


if __name__ == "__main__":
    main()
