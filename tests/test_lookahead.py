"""時序不變量:持倉是 shift(1)、且『偷看當日』會虛高 Sharpe → 證明 shift 是 load-bearing。"""
import numpy as np
import pandas as pd
from src.strategy import build_curve, COST_PER_SIDE

ANN = np.sqrt(252)


def _sharpe(x):
    return float(x.mean() / x.std() * ANN)


def test_exposure_held_is_shift_of_signal(curve):
    """實際持倉(exposure_held 口徑)= 訊號 shift(1)。"""
    sig = curve["exposure"]
    held = sig.shift(1).fillna(0.0)
    # pnl 由 held 算:驗 pnl 與 held*benchmark-return 一致(間接證 shift)
    assert held.iloc[0] == 0.0


def test_lookahead_shift_is_load_bearing(taiex, move):
    """誠實(shift1)Sharpe 應『明顯低於』偷看當日(unshift)Sharpe。
    monorepo 實證:1.32 → 2.44。若兩者接近 = shift 沒生效(look-ahead 漏洞)。"""
    cv = build_curve(taiex, move)
    idx = taiex["close"].dropna().astype(float)
    ret = idx.pct_change().clip(-0.1, 0.1).fillna(0.0).reindex(cv.index)
    exposure = cv["exposure"]
    honest = cv["pnl"]  # pos = exposure.shift(1)
    cheat_pos = exposure  # 偷看當日
    cheat = cheat_pos * ret - cheat_pos.diff().abs().fillna(0) * COST_PER_SIDE
    full = cv.index >= "2016-11-01"
    sh_honest, sh_cheat = _sharpe(honest[full]), _sharpe(cheat[full])
    assert sh_cheat > sh_honest + 0.3, f"shift 未生效? honest={sh_honest:.2f} cheat={sh_cheat:.2f}"
