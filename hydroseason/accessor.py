"""Pandas DataFrame accessor: ``df.hydroseason.<method>()``

Registers ``hydroseason`` as a pandas ``DataFrame`` accessor.
Import ``hydroseason`` once and all DataFrames gain the accessor.

Usage
-----
>>> import hydroseason
>>> df = pd.read_csv("monthly.csv")
>>> result = df.hydroseason.classify_rainfall_df()       # → DataFrame
>>> artifacts = df.hydroseason.classify_rainfall()       # → PipelineArtifacts
>>> fig = df.hydroseason.plot_timeline()
>>> fig = df.hydroseason.plot_dashboard()

Keyword arguments are forwarded to the underlying pipeline. For methods that
also produce a figure or report (``plot_dashboard``, ``generate_report``,
``export``), plot/report-only keywords (``title``, ``width``, ``height``,
``value_col``) are routed to the plot/report function and the rest go to the
pipeline.
"""

from __future__ import annotations

import pandas as pd


@pd.api.extensions.register_dataframe_accessor("hydroseason")
class HydroSeasonAccessor:
    """``df.hydroseason`` accessor — lazy import keeps registration cheap."""

    def __init__(self, pandas_obj: pd.DataFrame) -> None:
        self._df = pandas_obj

    def _get_cached_artifacts(self, **kwargs):
        try:
            data_hash = int(pd.util.hash_pandas_object(self._df, index=True).sum())
        except Exception:
            data_hash = None
        cache_key = (kwargs, len(self._df), tuple(self._df.columns), tuple(self._df.dtypes.astype(str)), data_hash)
        cache = getattr(self._df, "_hydroseason_cache", None)
        if cache is not None:
            cached_key, cached_arts = cache
            if cached_key == cache_key:
                return cached_arts

        from .pipeline import classify_rainfall
        arts = classify_rainfall(self._df, **kwargs)
        try:
            object.__setattr__(self._df, "_hydroseason_cache", (cache_key, arts))
        except Exception:
            pass
        return arts

    # ------------------------------------------------------------------ pipeline
    def classify_rainfall_df(self, **kwargs) -> pd.DataFrame:
        """Run the full pipeline and return just the result ``DataFrame``."""
        return self.classify_rainfall(**kwargs).result

    def classify_rainfall(self, **kwargs):
        """Run the full pipeline and return a :class:`PipelineArtifacts` bundle."""
        return self._get_cached_artifacts(**kwargs)

    # ------------------------------------------------------------------ plots
    def plot_timeline(self, **kwargs):
        """``plot_season_timeline`` after auto-running the pipeline if needed."""
        from .plot import plot_season_timeline
        if "SeasonType" not in self._df.columns:
            df = self.classify_rainfall_df()
        else:
            df = self._df
        return plot_season_timeline(df, **kwargs)

    def plot_agg_monthly_rainfall(self, fixed_monthly=None, **kwargs):
        """``plot_agg_monthly_rainfall`` - run pipeline if SeasonType column missing."""
        from .plot import plot_agg_monthly_rainfall
        if fixed_monthly is None and "SeasonType" not in self._df.columns:
            arts = self.classify_rainfall()
            return plot_agg_monthly_rainfall(arts.result, arts.fixed_monthly, **kwargs)
        return plot_agg_monthly_rainfall(self._df, fixed_monthly, **kwargs)

    def plot_monthly_climatology(self, fixed_monthly=None, **kwargs):
        """Backward-compatible alias for ``plot_agg_monthly_rainfall``."""
        return self.plot_agg_monthly_rainfall(fixed_monthly=fixed_monthly, **kwargs)

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
        arts = self.classify_rainfall(**{k: v for k, v in kwargs.items() if k not in _plot_keys})
        plot_kwargs = {k: v for k, v in kwargs.items() if k in _plot_keys}
        return plot_dashboard(arts, **plot_kwargs)

    # ------------------------------------------------------------------ report
    def display_summary(self, **kwargs):
        """Inline notebook summary card — regime badge + key diagnostics."""
        from .report import display_summary
        return display_summary(self.classify_rainfall(**kwargs))

    def generate_report(self, output_path="hydroseason_report.html", **kwargs):
        """Write a self-contained interactive HTML report and return its path."""
        from .report import generate_html_report
        _report_keys = {"title", "value_col"}
        arts = self.classify_rainfall(**{k: v for k, v in kwargs.items() if k not in _report_keys})
        report_kwargs = {k: v for k, v in kwargs.items() if k in _report_keys}
        return generate_html_report(arts, output_path, **report_kwargs)

    def export(self, output_dir="hydroseason_export", **kwargs):
        """Export full analysis bundle: HTML report plus CSV/JSON data.

        Returns the resolved output directory :class:`~pathlib.Path`.
        """
        from .report import export_bundle
        _export_keys = {"title", "value_col"}
        arts = self.classify_rainfall(**{k: v for k, v in kwargs.items() if k not in _export_keys})
        export_kwargs = {k: v for k, v in kwargs.items() if k in _export_keys}
        return export_bundle(arts, output_dir, **export_kwargs)

    # ------------------------------------------------------------------ diagnostics
    def diagnostics(self, **kwargs):
        """Return the ``DiagnosticsReport`` from the pipeline."""
        return self.classify_rainfall(**kwargs).diagnostics

    # ------------------------------------------------------------------ repr
    def __repr__(self) -> str:  # noqa: D105
        return f"<HydroSeasonAccessor rows={len(self._df)}>"
