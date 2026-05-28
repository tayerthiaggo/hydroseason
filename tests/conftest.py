from pathlib import Path

import pandas as pd
import pytest


@pytest.fixture
def fixture_csv_path() -> Path:
    return Path(__file__).parent / "fixtures" / "monthly_rainfall.csv"


@pytest.fixture
def monthly_df(fixture_csv_path: Path) -> pd.DataFrame:
    return pd.read_csv(fixture_csv_path)
