"""Self-contained Leaflet boundary maps for compact AOI display contexts."""

from __future__ import annotations

import html
import importlib.resources
import re
import warnings

from ._aoi_context import AOIContext


_SAFE_ELEMENT_ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]*\Z")
_DEFAULT_ELEMENT_ID = "hydroseason-aoi-map"


def _asset_text(filename: str) -> str:
    return (
        importlib.resources.files("hydroseason")
        .joinpath("_assets", filename)
        .read_text(encoding="utf-8")
    )


def _validate_element_id(element_id: str) -> None:
    if not isinstance(element_id, str) or not _SAFE_ELEMENT_ID.fullmatch(element_id):
        raise ValueError("element_id must start with a letter and contain only letters, digits, _ or -.")


def _validate_height(height_px: int) -> None:
    if type(height_px) is not int or height_px <= 0:
        raise ValueError("height_px must be a positive integer.")


def render_aoi_map_html(
    context: AOIContext,
    *,
    element_id: str,
    height_px: int = 360,
) -> str:
    """Return an inline Leaflet map fragment showing an AOI boundary."""
    _validate_element_id(element_id)
    _validate_height(height_px)

    leaflet_css = _asset_text("leaflet-1.9.4.css")
    leaflet_js = _asset_text("leaflet-1.9.4.min.js")
    display_name = html.escape(context.display_name, quote=True)
    geojson = context.geojson.replace("</", "<\\/")

    # Leaflet's CSS image URLs are unused: this fragment creates neither
    # markers nor layer controls, so no marker or layer-control images are needed.
    return f'''<style>{leaflet_css}</style>
<div id="{element_id}" class="hydroseason-aoi-map" role="region" aria-label="Map of {display_name} boundary" tabindex="0" style="height: {height_px}px"></div>
<p id="{element_id}-offline-notice" class="hydroseason-aoi-map-notice" aria-live="polite" hidden>The boundary remains available if tiles fail. Loading online tiles sends requests to OpenStreetMap and requires an internet connection.</p>
<script>{leaflet_js}</script>
<script>
(() => {{
  const map = L.map('{element_id}');
  const geojson = {geojson};
  const layer = L.geoJSON(geojson, {{
    style: {{color: '#d1495b', weight: 3, opacity: 1, fillOpacity: 0.08}}
  }}).addTo(map);
  map.fitBounds(layer.getBounds(), {{padding: [20, 20], maxZoom: 12}});
  const tiles = L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>'
  }}).addTo(map);
  tiles.on('tileerror', () => {{
    document.getElementById('{element_id}-offline-notice').hidden = false;
  }});
}})();
</script>'''


def display_aoi_map(context: AOIContext) -> bool:
    """Best-effort display of an AOI boundary map in an IPython frontend."""
    try:
        from IPython.display import HTML, display

        display(HTML(render_aoi_map_html(context, element_id=_DEFAULT_ELEMENT_ID)))
    except Exception as exc:  # optional notebook support must not block analysis
        warnings.warn(
            f"Could not display AOI map: {exc}",
            UserWarning,
            stacklevel=2,
        )
        return False
    return True
