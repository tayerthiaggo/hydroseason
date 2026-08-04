import numpy as np
import pandas as pd

from hydroseason import detect_hydrological_years, generate_html_report


def _seasonal_extent(n_years=3):
    index = pd.date_range("2018-01-01", periods=12 * n_years, freq="MS")
    month = index.month
    wet_amplitude = 40.0 * np.cos(2 * np.pi * (month - 2) / 12) + 50.0
    return pd.DataFrame({
        "extent_pct": wet_amplitude,
        "invalid_pct": 0.0
    }, index=index)


def test_generate_html_report(tmp_path):
    extent = _seasonal_extent(n_years=3)
    hy_df = detect_hydrological_years(extent)

    output_file = tmp_path / "report.html"
    result_path = generate_html_report(
        extent,
        hy_df,
        output_file,
        title="Test Report",
        subtitle="Example catchment (2018–2020)",
        quality_note="2 months flagged for invalid coverage above 10%.",
    )

    assert result_path == output_file.resolve()
    assert output_file.exists()

    html_content = output_file.read_text(encoding="utf-8")
    assert "Test Report" in html_content
    assert "Example catchment (2018–2020)" in html_content
    assert "quality-banner" in html_content
    assert "2 months flagged" in html_content
    assert "HY 2018" in html_content
    assert "HY 2019" in html_content
    assert "HY 2020" in html_content
    assert "Wet Peak" in html_content
    assert "Dry End" in html_content
    assert "svg" in html_content.lower()
    # Quality warnings must not become the H1 title.
    assert "<h1>2 months flagged" not in html_content
