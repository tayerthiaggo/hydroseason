from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).parents[1]


@pytest.fixture
def fitzroy_30m() -> pd.DataFrame:
    return pd.read_csv(
        ROOT / "case_studies" / "data" / "extent" / "fitzroy_river_wa_30m.csv",
        parse_dates=["date"],
    )
