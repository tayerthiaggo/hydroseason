"""Pandas DataFrame accessor: ``df.hydroseason.<method>()``

Registers ``hydroseason`` as a pandas ``DataFrame`` accessor.
Import ``hydroseason`` once and all DataFrames gain the accessor.

Usage
-----
>>> import hydroseason
>>> df = pd.read_csv("monthly.csv")
>>> result = df.hydroseason.classify()                   # → DataFrame
>>> artifacts = df.hydroseason.delineate()               # → PipelineArtifacts
>>> fig = df.hydroseason.plot_timeline()
>>> fig = df.hydroseason.plot_dashboard()

Keyword arguments are forwarded verbatim to the underlying pipeline / plot functions.
"""

from __future__ import annotations

import pandas as pd


@pd.api.extensions.register_dataframe_accessor("hydroseason")
class HydroSeasonAccessor:
    """``df.hydroseason`` accessor — lazy import keeps registration cheap."""

    def __init__(self, pandas_obj: pd.DataFrame) -> None:
        self._df = pandas_obj

    # ------------------------------------------------------------------ pipeline
    def classify(self, **kwargs) -> pd.DataFrame:
        """Run the full pipeline and return just the result ``DataFrame``."""
        from .pipeline import delineate_monthly_dataframe
        return delineate_monthly_dataframe(self._df, **kwargs).result

    def delineate(self, **kwargs):
        """Run the full pipeline and return a ``PipelineArtifacts`` namedtuple."""
        from .pipeline import delineate_monthly_dataframe
        return delineate_monthly_dataframe(self._df, **kwargs)

    # ------------------------------------------------------------------ plots
    def plot_timeline(self, **kwargs):
        """``plot_season_timeline`` after auto-running the pipeline if needed."""
        from .plot import plot_season_timeline
        if "SeasonType" not in self._df.columns:
            df = self.classify()
        else:
            df = self._df
        return plot_season_timeline(df, **kwargs)

    def plot_climatology(self, fixed_monthly=None, **kwargs):
        """``plot_monthly_climatology`` — run pipeline if SeasonType column missing."""
        from .plot import plot_monthly_climatology
        if fixed_monthly is None and "SeasonType" not in self._df.columns:
            arts = self.delineate()
            return plot_monthly_climatology(arts.result, arts.fixed_monthly, **kwargs)
        return plot_monthly_climatology(self._df, fixed_monthly, **kwargs)

    def plot_stl(self, **kwargs):
        """``plot_stl_decomposition``."""
        from .plot import plot_stl_decomposition
        return plot_stl_decomposition(self._df, **kwargs)

    def plot_annual(self, **kwargs):
        """``plot_annual_metrics``."""
        from .plot import plot_annual_metrics
        return plot_annual_metrics(self._df, **kwargs)

    def plot_dashboard(self, **kwargs):
        """``plot_dashboard`` — always runs the full pipeline."""
        from .plot import plot_dashboard
        _plot_keys = {"value_col", "title", "width", "height"}
        arts = self.delineate(**{k: v for k, v in kwargs.items() if k not in _plot_keys})
        plot_kwargs = {k: v for k, v in kwargs.items() if k in _plot_keys}
        return plot_dashboard(arts, **plot_kwargs)

    # ------------------------------------------------------------------ report
    def display_summary(self, **kwargs):
        """Inline notebook summary card — regime badge + key diagnostics."""
        from .report import display_summary
        return display_summary(self.delineate(**kwargs))

    def generate_report(self, output_path="hydroseason_report.html", **kwargs):
        """Write a self-contained interactive HTML report and return its path."""
        from .report import generate_html_report
        _report_keys = {"title", "value_col"}
        arts = self.delineate(**{k: v for k, v in kwargs.items() if k not in _report_keys})
        report_kwargs = {k: v for k, v in kwargs.items() if k in _report_keys}
        return generate_html_report(arts, output_path, **report_kwargs)

    # ------------------------------------------------------------------ diagnostics
    def diagnostics(self, **kwargs):
        """Return the ``DiagnosticsReport`` from the pipeline."""
        return self.delineate(**kwargs).diagnostics

    # ------------------------------------------------------------------ repr
    def __repr__(self) -> str:  # noqa: D105
        return f"<HydroSeasonAccessor rows={len(self._df)}>"
