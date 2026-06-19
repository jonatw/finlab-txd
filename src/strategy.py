"""TXD 擇時策略 — finlab-free 純函式版(從 finlab monorepo 搬出,參數凍結)。

TXD = TX 分級順勢×MOVE 槓桿 + DTP% 高波動關機濾網。
- spine = 收盤站上 MA60/120/200 的比例(0 / .33 / .67 / 1)
- lev   = MOVE < 自身 252 日中位 → 2x 加碼,否則 1x
- DTP   = Wilder-ATR(14)% 的 250 日百分位;昨日 ≥ top-4%(發瘋日)→ 今日空手
- 進場 T+1、成本 2bps/單邊。時序安全 by construction(exposure.shift(1)、DTP 用 t-1)。

唯一輸入 = 價格指數 OHLC(Yahoo ^TWII)+ MOVE(Yahoo ^MOVE)。不依賴 finlab。
與 monorepo `scripts/research/txd_trend_movevol_dtp.py` 邏輯逐位元一致(seed 重建 max|diff|=0)。
"""
from __future__ import annotations
import numpy as np
import pandas as pd

# 凍結參數(原作者值 / 標準 ATR 預設;改這裡 = 改策略 → 觸發 audit-on-change gate)
ATR_WIN, DTP_LOOKBACK, DTP_THRESH = 14, 250, 0.96
COST_PER_SIDE = 0.0002  # 2bps/單邊


def build_curve(taiex: pd.DataFrame, move: pd.Series) -> pd.DataFrame:
    """taiex: DataFrame(index=date, cols 至少含 high/low/close);move: Series(index=date)。
    回傳 curve DataFrame(strategy/benchmark/exposure/pnl/nav/dtp_gated),index=交易日。"""
    idx = taiex["close"].dropna().astype(float)
    hi = taiex["high"].reindex(idx.index).astype(float)
    lo = taiex["low"].reindex(idx.index).astype(float)
    cal = idx.index
    ret = idx.pct_change().clip(-0.1, 0.1).fillna(0.0)
    mv = move.reindex(cal, method="ffill")

    # 訊號(TX 基底)
    spine = pd.concat(
        [(idx > idx.rolling(w).mean()).astype(float) for w in (60, 120, 200)], axis=1
    ).mean(axis=1)
    lev = pd.Series(
        np.where(mv < mv.rolling(252, min_periods=120).quantile(0.5), 2.0, 1.0), index=cal
    )
    raw_exposure = (spine * lev).clip(0, 2)

    # DTP% 高波動關機濾網(Wilder RMA = 標準 ATR)
    tr = pd.concat(
        [hi - lo, (hi - idx.shift(1)).abs(), (lo - idx.shift(1)).abs()], axis=1
    ).max(axis=1)
    atr_pct = tr.ewm(alpha=1 / ATR_WIN, adjust=False).mean() / idx * 100
    dtp = atr_pct.rolling(DTP_LOOKBACK).apply(lambda x: (x.iloc[-1] >= x).mean(), raw=False)
    gate_sig = (dtp < DTP_THRESH).fillna(True)  # gate[D]=D 收盤判 D+1 可否交易
    exposure = raw_exposure * gate_sig

    # 回測(進場 T+1,pos=訊號 shift1=實際持倉)
    pos = exposure.shift(1).fillna(0.0)
    pnl = pos * ret - pos.diff().abs().fillna(0) * COST_PER_SIDE
    nav = (1 + pnl).cumprod()
    bench = (1 + ret).cumprod()

    return pd.DataFrame(
        {
            "strategy": nav,
            "benchmark": bench,
            "exposure": exposure,
            "pnl": pnl,
            "nav": nav,
            "dtp_gated": (~gate_sig.astype(bool)).astype(int),
        }
    )
