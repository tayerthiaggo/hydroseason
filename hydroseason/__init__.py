"""HydroSeason: remote-sensing-first hydro-year detection (migration in progress)."""

from importlib.metadata import PackageNotFoundError, version as _pkg_version

try:
    __version__ = _pkg_version("hydroseason")
except PackageNotFoundError:  # running from a source tree without install
    __version__ = "0.1.0"

__all__ = ["__version__"]
