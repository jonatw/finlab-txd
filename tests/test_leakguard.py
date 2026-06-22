"""leak guardrail util 的回歸測試 + 自我驗證(load-bearing 證明)。"""
import pandas as pd
import pytest

from src.strategy import build_curve
from leakguard import assert_no_lookahead


def test_build_curve_has_no_lookahead(taiex, move):
    """append 未來資料,exposure/dtp_gated 在 cut 前必須 bit-identical(build_curve 全因果)。"""
    cut = taiex.index[int(len(taiex) * 0.7)]
    mx = assert_no_lookahead(
        build_curve, taiex, move,
        cut=cut, cols=["exposure", "dtp_gated"], label="build_curve",
    )
    assert mx < 1e-9


def test_guardrail_catches_centered_rolling_leak(taiex, move):
    """自我驗證 ①:centered rolling 特徵(經典 SMC 洩漏,對照 BreakOutLiquiditySweep 的 center=True bug)→ 必抓到。
    用連續特徵(非二值化)才看得出 mean 被未來改變。"""
    def leaky_builder(tx, mv):
        c = tx["close"].astype(float)
        feat = c.rolling(41, center=True, min_periods=1).mean()  # ±20 bar 偷看未來
        return pd.DataFrame({"feat": feat}, index=c.index)

    cut = taiex.index[int(len(taiex) * 0.7)]
    with pytest.raises(AssertionError, match="LOOK-AHEAD LEAK"):
        assert_no_lookahead(leaky_builder, taiex, move, cut=cut, cols=["feat"], label="leaky_centered")


def test_guardrail_catches_future_shift_leak(taiex, move):
    """自我驗證 ②:直接用未來 bar(shift(-1))→ 邊界出現 NaN-vs-值 → NaN-aware 比較必抓到。"""
    def leaky_builder(tx, mv):
        c = tx["close"].astype(float)
        return pd.DataFrame({"feat": c.shift(-1)}, index=c.index)  # 用下一根

    cut = taiex.index[int(len(taiex) * 0.7)]
    with pytest.raises(AssertionError, match="LOOK-AHEAD LEAK"):
        assert_no_lookahead(leaky_builder, taiex, move, cut=cut, cols=["feat"], label="leaky_shift")
