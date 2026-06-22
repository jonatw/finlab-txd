"""P/C 反向擇時 paper-lane 訊號:look-ahead guardrail + 凍結規格回歸。

P/C 是平行 paper-lane 訊號(#133),但它一樣會產生績效數字 → 套同一套
leakguard 鐵律(append 未來資料,cut 前輸出必 bit-identical)。
"""
import numpy as np
import pandas as pd
import pytest

from src.pcr import build_pcr_curve, WINDOW, MIN_PERIODS, PCTILE
from leakguard import assert_no_lookahead


def test_pcr_curve_no_lookahead(taiex, pcr):
    """append 未來 P/C/價格後,cut 前的 signal/pos 必 bit-identical(全因果:trailing quantile + shift(1))。"""
    close = taiex["close"]
    cut = close.index[int(len(close) * 0.7)]
    mx = assert_no_lookahead(
        build_pcr_curve, close, pcr,
        cut=cut, cols=["signal", "pos"], label="pcr_curve",
    )
    assert mx < 1e-9


def test_pcr_pos_is_t_plus_1(taiex, pcr):
    """pos[D] 必等於 signal[D-1](T+1 持倉;當日訊號當日不可交易)。"""
    cv = build_pcr_curve(taiex["close"], pcr)
    expect = cv["signal"].shift(1).fillna(0.0)
    assert np.allclose(cv["pos"].to_numpy(), expect.to_numpy())


def test_pcr_contrarian_direction(taiex, pcr):
    """方向 = 反向:高 P/C(>p60)→ 做多。signal=1 的日子 P/C 應顯著高於 signal=0 的日子。"""
    cv = build_pcr_curve(taiex["close"], pcr).dropna(subset=["pcr", "threshold"])
    hi = cv.loc[cv["signal"] > 0.5, "pcr"].mean()
    lo = cv.loc[cv["signal"] < 0.5, "pcr"].mean()
    assert hi > lo, f"做多日 P/C({hi:.1f}) 應 > 空手日 P/C({lo:.1f})"


def test_pcr_frozen_params():
    """凍結參數防漂移(改這些 = 改策略身分,要明確意圖)。"""
    assert (WINDOW, MIN_PERIODS, PCTILE) == (252, 126, 0.60)


def test_pcr_signal_only_uses_trailing(taiex, pcr):
    """signal[D] 只能用 ≤D 的 P/C:截到某日重算,最後一個 signal 與全長同位置一致。"""
    close = taiex["close"]
    cut = close.index[int(len(close) * 0.8)]
    full = build_pcr_curve(close, pcr)
    past = build_pcr_curve(close[close.index <= cut], pcr[pcr.index <= cut])
    common = past.index.intersection(full.index)
    assert np.allclose(past.loc[common, "signal"].to_numpy(),
                       full.loc[common, "signal"].to_numpy(), equal_nan=True)
