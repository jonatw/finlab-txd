from pathlib import Path
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def taiex():
    return pd.read_csv(ROOT / "data/raw/taiex_twii.csv", parse_dates=["date"]).set_index("date")


@pytest.fixture(scope="session")
def move():
    return pd.read_csv(ROOT / "data/raw/move.csv", parse_dates=["date"]).set_index("date")["move"]


@pytest.fixture(scope="session")
def curve():
    return pd.read_csv(ROOT / "data/derived/curve.csv", parse_dates=["date"]).set_index("date")
