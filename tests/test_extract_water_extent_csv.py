import importlib.util
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "extract_water_extent_csv.py"


@pytest.fixture()
def mod():
    spec = importlib.util.spec_from_file_location("extract_water_extent_csv_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


def test_parser_defaults_to_30m_canonical_cache(mod):
    args = mod._build_arg_parser().parse_args(["--aoi", "data/Gilbert_river_buffer.geojson"])

    assert args.resolution == 30.0
    assert args.offline is False
    assert args.legacy_remote_path is False


def test_offline_and_legacy_remote_are_mutually_exclusive(mod):
    with pytest.raises(SystemExit):
        mod._build_arg_parser().parse_args([
            "--aoi", "data/Gilbert_river_buffer.geojson", "--offline", "--legacy-remote-path"
        ])


def test_wet_mask_flag_defaults_off_and_accepts_dea_stats():
    import scripts.extract_water_extent_csv as script

    parser = script._build_arg_parser()

    assert parser.parse_args([]).wet_mask == "off"
    assert parser.parse_args(["--wet-mask", "dea_stats"]).wet_mask == "dea_stats"

    with pytest.raises(SystemExit):
        parser.parse_args(["--wet-mask", "nonsense"])
