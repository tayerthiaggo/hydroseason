"""Contract tests for self-contained, display-only AOI boundary maps."""

import sys
import types

import pytest

from hydroseason._aoi_context import AOIContext


def _context(*, geojson=None, display_name="Fitzroy & Kimberley"):
    return AOIContext(
        geojson=geojson
        or (
            '{"type":"FeatureCollection","features":[{"type":"Feature",'
            '"properties":{},"geometry":{"type":"Polygon",'
            '"coordinates":[[[115,-32],[116,-32],[116,-31],[115,-32]]]}}]}'
        ),
        bounds_wgs84=(115.0, -32.0, 116.0, -31.0),
        display_name=display_name,
        feature_count=1,
    )


def test_renders_self_contained_accessible_boundary_map_with_required_tile_behaviour():
    """Removing the boundary or changing tile failure/privacy behaviour must fail."""
    from hydroseason._aoi_map import render_aoi_map_html

    html = render_aoi_map_html(_context(), element_id="overview-map", height_px=420)

    assert 'id="overview-map"' in html
    assert 'aria-label="Map of Fitzroy &amp; Kimberley boundary"' in html
    assert "height: 420px" in html
    assert "leaflet-1.9.4" not in html  # assets are inline, never linked by filename
    assert "<script src=" not in html
    assert "L.geoJSON" in html
    assert "color: '#d1495b'" in html
    assert "weight: 3" in html
    assert "opacity: 1" in html
    assert "fillOpacity: 0.08" in html
    assert "fitBounds(layer.getBounds(), {padding: [20, 20], maxZoom: 12})" in html
    assert "https://tile.openstreetmap.org/{z}/{x}/{y}.png" in html
    assert "maxZoom: 19" in html
    assert "OpenStreetMap contributors" in html
    assert "tileerror" in html
    assert "boundary remains available if tiles fail" in html
    assert "requests to OpenStreetMap" in html
    assert "internet connection" in html
    assert "L.marker" not in html
    assert "L.control.layers" not in html
    assert "L.tileLayer('data:" not in html


def test_feature_ids_are_visible_to_assistive_technology_and_bound_as_popups():
    from hydroseason._aoi_map import render_aoi_map_html

    context = AOIContext(
        geojson=(
            '{"type":"FeatureCollection","features":['
            '{"type":"Feature","geometry":{"type":"Polygon","coordinates":[]},'
            '"properties":{"id":"alpha"}},'
            '{"type":"Feature","geometry":{"type":"Polygon","coordinates":[]},'
            '"properties":{"id":"beta"}}]}'
        ),
        bounds_wgs84=(115.0, -32.0, 116.0, -31.0),
        display_name="Two AOIs",
        feature_count=2,
    )
    rendered = render_aoi_map_html(context, element_id="batch-map")
    assert "AOI boundaries: alpha, beta" in rendered
    assert "onEachFeature" in rendered
    assert "bindPopup" in rendered
    assert "textContent" in rendered


def test_escapes_display_name_and_script_terminators_in_geojson():
    """An injected name or closing script sequence must not escape the fragment."""
    from hydroseason._aoi_map import render_aoi_map_html

    html = render_aoi_map_html(
        _context(
            display_name='<img src=x onerror="alert(1)">',
            geojson='{"type":"FeatureCollection","name":"</script><script>alert(1)</script>"}',
        ),
        element_id="safe_map",
    )

    assert '&lt;img src=x onerror=&quot;alert(1)&quot;&gt;' in html
    assert "</script><script>alert(1)</script>" not in html
    assert "<\\/script><script>alert(1)<\\/script>" in html


@pytest.mark.parametrize("element_id", ["", "a b", "1map", "map\"name", "map<name>"])
def test_rejects_unsafe_map_element_ids(element_id):
    """Weakening element ID validation must fail for HTML/JavaScript-unsafe IDs."""
    from hydroseason._aoi_map import render_aoi_map_html

    with pytest.raises(ValueError, match="element_id"):
        render_aoi_map_html(_context(), element_id=element_id)


@pytest.mark.parametrize("height_px", [0, -1, 1.5, True, "360"])
def test_rejects_non_positive_integer_map_heights(height_px):
    """Accepting an invalid CSS height must fail instead of rendering unsafe markup."""
    from hydroseason._aoi_map import render_aoi_map_html

    with pytest.raises(ValueError, match="height_px"):
        render_aoi_map_html(_context(), element_id="map", height_px=height_px)


def test_display_lazily_uses_ipython_to_show_the_same_map_fragment(monkeypatch):
    """Moving the IPython import to module scope or rendering a different fragment must fail."""
    from hydroseason import _aoi_map

    displayed = []

    class FakeHTML:
        def __init__(self, value):
            self.value = value

    display_module = types.ModuleType("IPython.display")
    display_module.HTML = FakeHTML
    display_module.display = displayed.append
    ipython_module = types.ModuleType("IPython")
    ipython_module.display = display_module
    monkeypatch.setitem(sys.modules, "IPython", ipython_module)
    monkeypatch.setitem(sys.modules, "IPython.display", display_module)

    assert _aoi_map.display_aoi_map(_context()) is True
    assert len(displayed) == 1
    assert isinstance(displayed[0], FakeHTML)
    assert "L.geoJSON" in displayed[0].value


def test_display_warns_and_returns_false_when_ipython_is_unavailable_or_fails(monkeypatch):
    """Propagating optional-display failures must fail instead of preserving analysis use."""
    from hydroseason import _aoi_map

    monkeypatch.setitem(sys.modules, "IPython", None)
    monkeypatch.delitem(sys.modules, "IPython.display", raising=False)
    with pytest.warns(UserWarning, match="IPython"):
        assert _aoi_map.display_aoi_map(_context()) is False

    def fail_display(_value):
        raise RuntimeError("notebook closed")

    display_module = types.ModuleType("IPython.display")
    display_module.HTML = lambda value: value
    display_module.display = fail_display
    ipython_module = types.ModuleType("IPython")
    ipython_module.display = display_module
    monkeypatch.setitem(sys.modules, "IPython", ipython_module)
    monkeypatch.setitem(sys.modules, "IPython.display", display_module)
    with pytest.warns(UserWarning, match="notebook closed"):
        assert _aoi_map.display_aoi_map(_context()) is False
