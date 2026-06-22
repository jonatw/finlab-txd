"""共用 look-ahead guardrail(pytest util)。

移植自 ZiadFrancis `Reinforcement_Trading_Part_2/leakage_checks.py` 的
`assert_feature_stability_when_future_appended`,一般化成「任意 builder」:

    past = builder(*[input 截到 cut 為止])
    full = builder(*input 全長)
    斷言 past 與 full 在 cut 之前的指定欄位 **完全一致**。

任何用到未來 bar 的計算 —— centered rolling、scaler fit 全序列、bfill、
shift(-N) 漏進特徵、用整段 min/max 正規化 —— 都會讓「過去那段」在 full 版本裡改變,
被這個斷言當場抓到。比事後 audit 更早、更機械化,適合掛進每個策略/特徵函式的單元測試。

用法:
    from leakguard import assert_no_lookahead
    assert_no_lookahead(build_curve, taiex, move,
                        cut=taiex.index[int(len(taiex)*0.7)],
                        cols=["exposure", "dtp_gated"])
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _truncate(x, cut):
    if isinstance(x, (pd.DataFrame, pd.Series)):
        return x[x.index <= cut]
    return x


def assert_no_lookahead(builder, *inputs, cut, cols=None, atol=1e-9, label="builder", min_overlap=50):
    """builder(*inputs) -> DataFrame/Series(時間排序 index)。

    cut: Timestamp。把每個 pandas input 截到 `<= cut` 再 build,與全長 build 比較 cut 之前的輸出。
    回傳 max|past-full|(無洩漏時 ~0)。發現過去輸出被未來資料改變 → AssertionError。
    """
    cut = pd.Timestamp(cut)
    past = builder(*[_truncate(x, cut) for x in inputs])
    full = builder(*inputs)
    if isinstance(past, pd.Series):
        past = past.to_frame("value")
    if isinstance(full, pd.Series):
        full = full.to_frame("value")

    idx = past.index.intersection(full.index)
    idx = idx[idx <= cut]
    assert len(idx) >= min_overlap, f"{label}: 截斷後重疊樣本太少({len(idx)} < {min_overlap})— 換個 cut"

    use = list(cols) if cols is not None else [c for c in past.columns if c in full.columns]
    a = past.loc[idx, use].astype(float)
    b = full.loc[idx, use].astype(float)

    def _maxdiff(s1, s2):
        # NaN-aware:兩邊都 NaN(同 warmup)→ 0;一邊 NaN 一邊有值(如 shift(-N) 漏未來)→ inf;否則 abs 差。
        both_nan = s1.isna() & s2.isna()
        one_nan = s1.isna() ^ s2.isna()
        d = (s1 - s2).abs().mask(both_nan, 0.0).mask(one_nan, np.inf)
        arr = d.to_numpy()
        return float(np.nanmax(arr)) if arr.size else 0.0

    per_col = {c: _maxdiff(a[c], b[c]) for c in use}
    mx = max(per_col.values()) if per_col else 0.0

    assert mx <= atol, (
        f"{label}: LOOK-AHEAD LEAK — append 未來資料後,cut({cut.date()}) 之前的輸出改變了。"
        f" max|past-full|={mx:.3e} > atol={atol}。受影響欄位="
        f"{[c for c, d in per_col.items() if d > atol]}"
    )
    return mx
