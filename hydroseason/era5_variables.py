"""ERA5 variable adapter registry.

Each entry describes how to fetch and convert one variable from an ERA5 zarr store
to a tidy monthly DataFrame. Add new variables here rather than parameterising fetch().

Conventions:
- ``era5_name`` : variable name in the zarr store (and any common alias).
- ``aggregation``: how to aggregate from the native (hourly) timestep to monthly:
    "sum"  → total over the month (e.g. precipitation, evaporation)
    "mean" → average over the month (e.g. temperature)
- ``unit_factor``, ``unit_offset``: applied as ``value * unit_factor + unit_offset``
  to the native units, after aggregation.
- ``unit_label``: human-readable unit string written to the output column.
- ``out_column``: tidy DataFrame column name.

ERA5 hourly conventions:
- ``total_precipitation`` and ``evaporation`` are in metres per hour. Summing 24*N hourly
  values gives metres per month → multiply by 1000 to get mm.
- ``2m_temperature`` is in Kelvin → subtract 273.15 to get °C.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ERA5Variable:
    key: str
    era5_name: str
    aggregation: str       # "sum" | "mean"
    unit_factor: float
    unit_offset: float
    unit_label: str
    out_column: str
    aliases: tuple[str, ...] = ()


_REGISTRY: dict[str, ERA5Variable] = {}


def register(var: ERA5Variable) -> None:
    _REGISTRY[var.key] = var
    for alias in var.aliases:
        _REGISTRY[alias] = var


def get(key: str) -> ERA5Variable:
    if key not in _REGISTRY:
        raise KeyError(
            f"Unknown ERA5 variable '{key}'. Available: {sorted(set(v.key for v in _REGISTRY.values()))}"
        )
    return _REGISTRY[key]


def available() -> list[str]:
    return sorted(set(v.key for v in _REGISTRY.values()))


# ---------------------------------------------------------------------------
# Built-in adapters
# ---------------------------------------------------------------------------
register(
    ERA5Variable(
        key="rainfall",
        era5_name="total_precipitation",
        aggregation="sum",
        unit_factor=1000.0,
        unit_offset=0.0,
        unit_label="mm",
        out_column="Rainfall_mm",
        aliases=("precipitation", "tp", "total_precipitation"),
    )
)

register(
    ERA5Variable(
        key="evaporation",
        era5_name="evaporation",
        aggregation="sum",
        unit_factor=1000.0,
        unit_offset=0.0,
        unit_label="mm",
        out_column="Evaporation_mm",
        aliases=("e",),
    )
)

register(
    ERA5Variable(
        key="temperature",
        era5_name="2m_temperature",
        aggregation="mean",
        unit_factor=1.0,
        unit_offset=-273.15,
        unit_label="°C",
        out_column="Temperature_C",
        aliases=("t2m", "2m_temperature"),
    )
)
