"""資料完整性:OHLC 自洽、無斷層、MOVE 不過時。catch Yahoo 壞 tick / 漏抓。"""
import pandas as pd

TOL = 1e-6


def test_ohlc_consistent(taiex):
    assert (taiex["high"] >= taiex["low"] - TOL).all(), "high < low"
    assert (taiex["high"] >= taiex["close"] - TOL).all(), "high < close"
    assert (taiex["close"] >= taiex["low"] - TOL).all(), "close < low"
    assert (taiex["high"] >= taiex["open"] - TOL).all() and (taiex["open"] >= taiex["low"] - TOL).all()
    assert (taiex["close"] > 0).all()


def test_no_nan_close(taiex):
    assert taiex["close"].notna().all()


def test_no_crazy_daily_move(taiex):
    chg = taiex["close"].pct_change().abs().dropna()
    assert (chg < 0.11).all(), f"單日漲跌 ≥11%(壞 tick?)最大 {chg.max():.3f}"


def test_move_positive(move):
    assert (move > 0).all() and move.notna().all()


def test_move_freshness(taiex, move):
    """MOVE(美債, 晚台股 ~1 日)落後台股最新日 ≤ 5 個交易日。"""
    lag = pd.bdate_range(move.index[-1], taiex.index[-1]).size - 1
    assert lag <= 5, f"MOVE 落後 {lag} 個交易日(抓取可能壞了)"


def test_dates_sorted_unique(taiex, move):
    for s in (taiex.index, move.index):
        assert s.is_monotonic_increasing and s.is_unique
