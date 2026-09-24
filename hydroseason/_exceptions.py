"""Domain exceptions for HydroSeason scientific boundary routing and fallback."""

from __future__ import annotations

__all__ = ["BoundaryNotSupported"]


class BoundaryNotSupported(ValueError):
    """Observed evidence cannot support annual boundaries under the active policy."""