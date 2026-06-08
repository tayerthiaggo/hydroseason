"""Generate the README/docs static-method comparison image."""

from __future__ import annotations

import calendar
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.lines as mlines
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import pandas as pd

from hydroseason import classify_rainfall


ROOT = Path(__file__).resolve().parents[1]
INPUT_CSV = ROOT / "data" / "monthly_rainfall.csv"
OUTPUT_PNG = ROOT / "docs" / "assets" / "images" / "static-vs-hydroseason.png"

WET = "#1565C0"
DRY = "#EF3800"
UNCLASSIFIED = "#9E9E9E"
SMOOTH_LINE = "#212121"
YEAR_LINE = "#757575"
WET_BAND = "#DCEEFF"
DRY_BAND = "#FFE2DA"
WET_BAND_ALPHA = 0.58
DRY_BAND_ALPHA = 0.62


def _season_colour(season: str) -> str:
    if season == "Wet":
        return WET
    if season == "Dry":
        return DRY
    return UNCLASSIFIED


def _season_band_colour(season: str) -> str | None:
    if season == "Wet":
        return WET_BAND
    if season == "Dry":
        return DRY_BAND
    return None


def _month_to_fixed_season(fixed_monthly: pd.DataFrame) -> dict[int, str]:
    seasons = fixed_monthly["Season"].astype(str).tolist()
    if len(seasons) != 12:
        raise ValueError("Expected 12 monthly rows in fixed climatology output.")
    return {month: seasons[month - 1] for month in range(1, 13)}


def _select_display_window(result: pd.DataFrame) -> tuple[pd.Timestamp, pd.Timestamp]:
    min_date = pd.to_datetime(result["Date"]).min()
    max_date = pd.to_datetime(result["Date"]).max()
    window_start = pd.Timestamp(year=max_date.year - 7, month=1, day=1)
    return max(min_date, window_start), max_date


def _boundary_before(dates: pd.Series, index: int) -> pd.Timestamp:
    if index <= 0:
        return dates.iloc[0] - (dates.iloc[1] - dates.iloc[0]) / 2
    return dates.iloc[index - 1] + (dates.iloc[index] - dates.iloc[index - 1]) / 2


def _boundary_after(dates: pd.Series, index: int) -> pd.Timestamp:
    if index >= len(dates) - 1:
        return dates.iloc[-1] + (dates.iloc[-1] - dates.iloc[-2]) / 2
    return dates.iloc[index] + (dates.iloc[index + 1] - dates.iloc[index]) / 2


def _boundary_at_date(dates: pd.Series, date: pd.Timestamp) -> pd.Timestamp:
    matches = dates[dates == date]
    if matches.empty:
        return date
    return _boundary_before(dates, int(matches.index[0]))


def _draw_season_bands(ax, dates: pd.Series, seasons: list[str]) -> None:
    if len(dates) == 0:
        return

    run_start = 0
    for i in range(1, len(dates) + 1):
        if i == len(dates) or seasons[i] != seasons[run_start]:
            colour = _season_band_colour(seasons[run_start])
            if colour is not None:
                alpha = WET_BAND_ALPHA if seasons[run_start] == "Wet" else DRY_BAND_ALPHA
                x0 = _boundary_before(dates, run_start)
                x1 = _boundary_after(dates, i - 1)
                ax.axvspan(x0, x1, color=colour, alpha=alpha, lw=0, zorder=0)
            run_start = i


def _draw_panel(
    ax,
    df: pd.DataFrame,
    seasons: list[str],
    title: str,
    *,
    smoothed: pd.Series | None = None,
) -> None:
    dates = pd.to_datetime(df["Date"])
    colours = [_season_colour(season) for season in seasons]

    _draw_season_bands(ax, dates.reset_index(drop=True), seasons)
    ax.bar(
        dates,
        df["Rainfall_mm"],
        width=24,
        color=colours,
        edgecolor="white",
        linewidth=0.7,
        zorder=2,
    )
    if smoothed is not None:
        ax.plot(
            dates,
            smoothed,
            color=SMOOTH_LINE,
            linewidth=1.2,
            linestyle="--",
            zorder=3,
            label="Smoothed",
        )
    ax.set_title(title, loc="left", fontsize=13, fontweight="bold", pad=10)
    ax.set_ylabel("Monthly rainfall (mm)")
    ax.grid(axis="both", color="#EEEEEE", linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color("#B0BEC5")
    ax.set_ylim(0, max(df["Rainfall_mm"]) * 1.18)
    dates_reset = dates.reset_index(drop=True)
    ax.set_xlim(
        _boundary_before(dates_reset, 0),
        _boundary_after(dates_reset, len(dates_reset) - 1),
    )


def main() -> None:
    raw = pd.read_csv(INPUT_CSV)
    raw["Date"] = pd.to_datetime(raw["Date"])

    artifacts = classify_rainfall(raw)
    result = artifacts.result.copy()
    result["Date"] = pd.to_datetime(result["Date"])
    smoothed = result["Smoothed"] if "Smoothed" in result.columns else None
    start_month = int(artifacts.diagnostics.hydro_year_start_month or 1)
    fixed_season_map = _month_to_fixed_season(artifacts.fixed_monthly)

    window_start, window_end = _select_display_window(result)
    raw = raw.loc[raw["Date"].between(window_start, window_end)].copy()
    result = result.loc[result["Date"].between(window_start, window_end)].copy()
    if smoothed is not None:
        smoothed = smoothed.loc[result.index]

    static_seasons = [fixed_season_map[int(month)] for month in raw["Month"].astype(int)]

    hy_shift = result["Hydro_Year"].ne(result["Hydro_Year"].shift())
    wet_onset = result["SeasonType"].eq("Wet") & result["SeasonType"].ne(result["SeasonType"].shift())
    mismatched_hy_starts = result.loc[hy_shift & ~wet_onset].iloc[1:]
    if not mismatched_hy_starts.empty:
        bad_dates = ", ".join(mismatched_hy_starts["Date"].dt.strftime("%Y-%m").tolist())
        raise RuntimeError(
            "HydroYear boundaries in the README comparison must align with "
            f"Wet onsets. Mismatched starts: {bad_dates}"
        )

    fig, axes = plt.subplots(
        2,
        1,
        figsize=(13, 7.0),
        sharex=True,
    )
    fig.subplots_adjust(left=0.075, right=0.985, top=0.88, bottom=0.1, hspace=0.34)
    fig.patch.set_facecolor("white")
    fig.suptitle(
        "Calendar seasons can tell a different story than rainfall-derived hydrological years",
        fontsize=15,
        fontweight="bold",
        x=0.02,
        ha="left",
    )

    _draw_panel(
        axes[0],
        raw,
        static_seasons,
        "Static climatology baseline: fixed Wet/Dry months and fixed year starts",
        smoothed=smoothed,
    )
    _draw_panel(
        axes[1],
        result,
        result["SeasonType"].astype(str).tolist(),
        "HydroSeason: Wet/Dry months and hydrological-year starts derived from rainfall",
        smoothed=smoothed,
    )

    raw_dates = pd.to_datetime(raw["Date"]).reset_index(drop=True)
    result_dates = pd.to_datetime(result["Date"]).reset_index(drop=True)

    static_boundary_dates = raw.loc[raw["Month"].eq(start_month), "Date"]
    for boundary_date in static_boundary_dates:
        line_x = _boundary_at_date(raw_dates, pd.Timestamp(boundary_date))
        axes[0].axvline(
            line_x,
            color=YEAR_LINE,
            linestyle=":",
            linewidth=1.0,
            alpha=0.95,
            zorder=4,
        )
    full_result = artifacts.result.copy()
    full_result["Date"] = pd.to_datetime(full_result["Date"])
    hydro_starts = full_result.loc[
        full_result["Hydro_Year"] != full_result["Hydro_Year"].shift(),
        ["Date", "Hydro_Year"],
    ]
    hydro_starts = hydro_starts.loc[hydro_starts["Date"].between(window_start, window_end)]
    for _, row in hydro_starts.iterrows():
        line_x = _boundary_at_date(result_dates, row["Date"])
        axes[1].axvline(
            line_x,
            color=YEAR_LINE,
            linestyle=":",
            linewidth=1.0,
            alpha=0.95,
            zorder=4,
        )
        axes[1].text(
            line_x + pd.Timedelta(days=12),
            axes[1].get_ylim()[1] * 0.92,
            f"HY {int(row['Hydro_Year'])}",
            fontsize=9,
            color=YEAR_LINE,
            va="top",
        )

    axes[1].xaxis.set_major_locator(mdates.MonthLocator(interval=6))
    axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    axes[1].tick_params(axis="x", rotation=0)

    legend = [
        mpatches.Patch(color=WET, label="Wet"),
        mpatches.Patch(color=DRY, label="Dry"),
        mpatches.Patch(color=UNCLASSIFIED, label="Unclassified"),
        mlines.Line2D([], [], color=SMOOTH_LINE, linestyle="--", label="Smoothed"),
    ]
    axes[0].legend(
        handles=legend,
        ncol=4,
        frameon=False,
        loc="upper center",
        bbox_to_anchor=(0.72, 1.02),
    )

    fig.text(
        0.02,
        0.025,
        (
            f"Bundled example-report dataset subset ({window_start:%Y-%m} to {window_end:%Y-%m}). "
            f"Static baseline uses fixed month classes from long-term climatology and a fixed "
            f"hydrological-year start in {calendar.month_abbr[start_month]}."
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
