"""Frozen direct-profile trough refinement policy (introduced in HydroSeason v0.2.0)."""
from hydroseason._trough_refinement import TroughRefinementPolicy

TROUGH_REFINEMENT_POLICY = TroughRefinementPolicy(
    huber_k=1.345,
    profile_loss_cutoff=0.05,
    pulse_z=1.5,
    version="direct_profile_combined_v1",
    delta_rel=0.05,
    l_uncertainty_k=2.0,
    scale_mode="combined",
)

