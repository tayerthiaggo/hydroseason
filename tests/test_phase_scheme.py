import pytest

from hydroseason._phase_scheme import resolve_phase_scheme


def test_omitted_scheme_defaults_to_two_phase():
    assert resolve_phase_scheme() == "two_phase"


@pytest.mark.parametrize(
    ("legacy", "canonical"),
    [("cycle_relative", "four_phase"), ("rule_based", "four_phase"), ("none", "none")],
)
def test_legacy_models_map_with_deprecation(legacy, canonical):
    with pytest.warns(DeprecationWarning, match="phase_model"):
        assert resolve_phase_scheme(phase_model=legacy) == canonical


def test_canonical_and_legacy_selectors_cannot_be_combined():
    with pytest.raises(ValueError, match="phase_scheme and phase_model"):
        resolve_phase_scheme(phase_scheme="two_phase", phase_model="rule_based")


def test_unknown_canonical_scheme_is_rejected():
    with pytest.raises(ValueError, match="phase_scheme"):
        resolve_phase_scheme(phase_scheme="six_phase")
