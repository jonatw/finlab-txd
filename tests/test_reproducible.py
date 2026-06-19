"""數字正確 tier-1:curve 能從 raw 逐位元重生 + golden 錨點不漂移。"""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from src.strategy import build_curve

ROOT = Path(__file__).resolve().parents[1]


def test_curve_reproducible_from_raw(taiex, move, curve):
    """raw → strategy == 已存 curve.csv(逐位元)。"""
    rebuilt = build_curve(taiex, move)
    common = rebuilt.index.intersection(curve.index)
    assert len(common) == len(curve), "重建與存檔日期不一致"
    for c in curve.columns:
        d = float((rebuilt.loc[common, c] - curve.loc[common, c]).abs().max())
        assert d < 1e-6, f"欄 {c} 重生不符 max|diff|={d:.2e}"


def test_golden_anchors(curve):
    """凍結錨點(as_of 切片)不變 — 防數字悄悄漂移。"""
    exp = json.loads((ROOT / "data/golden/expected.json").read_text())
    asof = pd.Timestamp(exp["as_of"])
    sub = curve[curve.index <= asof]
    nav = sub["strategy"]
    ann = np.sqrt(252)
    sharpe = float(sub["pnl"].mean() / sub["pnl"].std() * ann)
    n = (1 + sub["pnl"]).cumprod()
    mdd = float((n / n.cummax() - 1).min() * 100)
    assert abs(float(nav.iloc[-1]) - exp["nav_final"]) < 1e-4
    assert abs(sharpe - exp["sharpe_full_1999"]) < 1e-4
    assert abs(mdd - exp["mdd_full_1999_pct"]) < 1e-3
    assert int(sub["dtp_gated"].sum()) == exp["dtp_gated_days"]
    for d, v in exp["nav_at"].items():
        assert abs(float(nav.asof(pd.Timestamp(d))) - v) < 1e-4, f"nav@{d}"
