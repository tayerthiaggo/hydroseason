import pytest

from hydroseason._phase_scheme import resolve_phase_scheme


def test_omitted_scheme_defaults_to_two_phase():
    assert resolve_phase_scheme() == "two_phase"


def test_unknown_canonical_scheme_is_rejected():
    with pytest.raises(ValueError, match="phase_scheme"):
        resolve_phase_scheme(phase_scheme="six_phase")
