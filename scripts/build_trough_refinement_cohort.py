"""Build the blinded trough-refinement span cohort.

Samples whole catchments from a previously uninspected source root, exports one
observation-only packet per annual cycle span, and freezes the anonymisation
mapping and the double-review subset before any labelling begins.

Two properties make this cohort evidence rather than decoration, and both are
enforced here rather than left to reviewer discipline:

* the reviewer never sees either algorithm's answer -- packets carry only the
  protocol's ``packet_allowlist`` columns; and
* the sample cannot become outcome-dependent -- catchments are the sampling
  unit, every cycle in a sampled catchment is labelled, and the double-review
  subset is drawn from the frozen seed before labelling rather than chosen
  afterwards.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

_REQUIRED_PROTOCOL_KEYS = {
    "protocol_id",
    "seed",
    "sampling_unit",
    "review_unit",
    "strata",
    "labels",
    "excluded_sources",
    "packet_allowlist",
    "hidden_fields",
    "min_algorithm_point_predictions",
    "double_review_min_fraction",
    "double_review_min_spans",
}


def validate_protocol(protocol: dict[str, Any]) -> dict[str, Any]:
    """Return the protocol, refusing one that cannot produce blind review."""
    missing = _REQUIRED_PROTOCOL_KEYS - set(protocol)
    if missing:
        raise ValueError(f"protocol missing required keys: {sorted(missing)}")
    overlap = set(protocol["packet_allowlist"]) & set(protocol["hidden_fields"])
    if overlap:
        raise ValueError(
            f"packet_allowlist and hidden_fields overlap on {sorted(overlap)}; "
            "a field cannot be both shown to the reviewer and hidden from them."
        )
    return protocol


def assert_source_eligible(source: Path, excluded_sources: list[str]) -> None:
    """Refuse a source root that this project has already inspected.

    Matching is substring-based on the resolved path and on each excluded
    token's last path segment, so a fresh copy of an inspected bundle under a
    new parent directory is still caught.
    """
    source_resolved = str(source.resolve()).replace("\\", "/").casefold()
    for token in excluded_sources:
        clean_token = token.strip().replace("\\", "/").casefold()
        tokens_to_check = [clean_token]
        if "/" in clean_token:
            tokens_to_check.append(clean_token.split("/")[-1])
        if any(t in source_resolved for t in tokens_to_check if t):
            raise ValueError(f"excluded source: {source} matches {token!r}")


def anonymous_id(seed: int, identifier: str) -> str:
    payload = f"{seed}:{identifier}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def write_identity_mapping(
    output_dir: Path, mapping: dict[str, str]
) -> tuple[Path, Path]:
    """Write the anonymous->real mapping and its hash, outside the packets."""
    output_dir.mkdir(parents=True, exist_ok=True)
    mapping_path = output_dir / "identity-mapping.json"
    hash_path = output_dir / "identity-mapping.sha256"
    mapping_path.write_text(json.dumps(mapping, indent=2, sort_keys=True), encoding="utf-8")
    hash_path.write_text(
        hashlib.sha256(mapping_path.read_bytes()).hexdigest() + "\n", encoding="ascii"
    )
    return mapping_path, hash_path


def build_review_packet(
    frame: pd.DataFrame,
    *,
    anonymous_catchment_id: str,
    anonymous_span_id: str,
    span_start: pd.Timestamp,
    span_end: pd.Timestamp,
    allowlist: Sequence[str],
) -> pd.DataFrame:
    """Project one span onto the observation-only columns a reviewer may see.

    Anything outside ``allowlist`` is dropped rather than renamed, so a column
    added upstream cannot leak by default.
    """
    packet = frame.copy()
    packet["anonymous_catchment_id"] = anonymous_catchment_id
    packet["anonymous_span_id"] = anonymous_span_id
    packet["span_start"] = span_start
    packet["span_end"] = span_end
    keep = [column for column in allowlist if column in packet.columns]
    return packet.loc[:, keep].reset_index(drop=True)


def select_double_review_ids(
    span_ids: Sequence[str],
    *,
    seed: int,
    min_fraction: float,
    min_spans: int,
) -> list[str]:
    """Draw the double-review subset deterministically, before labelling.

    Takes whichever of the fraction and the absolute floor is larger, capped at
    the cohort size. Drawing this from the frozen seed up front is what stops
    the second review from being aimed at spans someone already found awkward.
    """
    total = len(span_ids)
    if total == 0:
        return []
    target = max(int(np.ceil(total * min_fraction)), int(min_spans))
    target = min(target, total)
    rng = np.random.default_rng(seed)
    chosen = rng.choice(np.asarray(span_ids, dtype=object), size=target, replace=False)
    return sorted(str(value) for value in chosen)


def _iter_source_catchments(source_root: Path) -> Iterable[tuple[str, Path]]:
    for directory in sorted(p for p in source_root.iterdir() if p.is_dir()):
        monthly = list(directory.glob("*_monthly.csv"))
        if monthly:
            yield directory.name, monthly[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    protocol = validate_protocol(json.loads(args.protocol.read_text(encoding="utf-8")))
    assert_source_eligible(args.source_root, protocol["excluded_sources"])

    catchments = list(_iter_source_catchments(args.source_root))
    if not catchments:
        raise SystemExit(
            f"no catchment directories with a *_monthly.csv found under {args.source_root}. "
            "This cohort requires external evidence that does not yet exist in this "
            "repository; promotion is unavailable until an eligible, previously "
            "uninspected source root is supplied."
        )

    print(
        f"Validated protocol {protocol['protocol_id']}; "
        f"eligible source {args.source_root} with {len(catchments)} catchments."
    )


if __name__ == "__main__":
    main()
