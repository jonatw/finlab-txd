"""curve.csv → metrics_daily.csv(各窗 Sharpe/CAGR/MDD 時序)+ site/data/metrics.json。

凍結策略下,開口窗指標會因資料延伸漂移(全期≈不動、滾動 1 年會晃、MDD 單向棘輪)。
此檔每日全量重算(確定性、可重生)。git diff 只會多最後一列;若歷史列也變 = Yahoo 回溯修訂(資料警報)。
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CURVE = ROOT / "data" / "derived" / "curve.csv"
OUT_CSV = ROOT / "data" / "derived" / "metrics_daily.csv"
OUT_JSON = ROOT / "site" / "data" / "metrics.json"
ANN = np.sqrt(252)


def _expanding_window(pnl: pd.Series, start: str | None) -> pd.DataFrame:
    """從 start(None=全期)起算的『截至每日』Sharpe/CAGR/MDD(向量化)。"""
    p = pnl if start is None else pnl[pnl.index >= start]
    n = pd.Series(np.arange(1, len(p) + 1), index=p.index)
    mean, std = p.expanding().mean(), p.expanding().std()
    sharpe = mean / std * ANN
    nav = (1 + p).cumprod()
    cagr = (nav ** (252 / n) - 1) * 100
    mdd = (nav / nav.cummax() - 1).cummin() * 100
    return pd.DataFrame({"sharpe": sharpe, "cagr": cagr, "mdd": mdd})


def build_metrics() -> pd.DataFrame:
    cv = pd.read_csv(CURVE, parse_dates=["date"]).set_index("date")
    pnl = cv["pnl"].astype(float)
    full = _expanding_window(pnl, None)
    w2016 = _expanding_window(pnl, "2016-11-01")
    woos = _expanding_window(pnl, "2022-01-01")
    roll1y_sh = pnl.rolling(252).mean() / pnl.rolling(252).std() * ANN
    m = pd.DataFrame({
        "n": np.arange(1, len(cv) + 1),
        "sharpe_full": full["sharpe"], "cagr_full": full["cagr"], "mdd_full": full["mdd"],
        "sharpe_2016": w2016["sharpe"].reindex(cv.index), "cagr_2016": w2016["cagr"].reindex(cv.index),
        "sharpe_oos2022": woos["sharpe"].reindex(cv.index),
        "sharpe_1y": roll1y_sh,
        "exposure_avg": cv["exposure"].shift(1).expanding().mean(),
    }, index=cv.index).round(4)
    m.index.name = "date"
    return m


def main():
    m = build_metrics()
    m.to_csv(OUT_CSV)
    # 前端時序圖:2017 起(短窗成熟後)
    plot = m[m.index >= "2017-01-01"]
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps({
        "updated": str(m.index[-1].date()),
        "date": [str(d.date()) for d in plot.index],
        "sharpe_full": [None if pd.isna(x) else float(x) for x in plot["sharpe_full"]],
        "sharpe_2016": [None if pd.isna(x) else float(x) for x in plot["sharpe_2016"]],
        "sharpe_oos2022": [None if pd.isna(x) else float(x) for x in plot["sharpe_oos2022"]],
        "sharpe_1y": [None if pd.isna(x) else float(x) for x in plot["sharpe_1y"]],
    }, separators=(",", ":")))
    last = m.iloc[-1]
    print(f"✓ metrics_daily: {len(m)} 列 → {m.index[-1].date()} | "
          f"Sharpe full={last.sharpe_full:.2f} 2016={last.sharpe_2016:.2f} OOS={last.sharpe_oos2022:.2f} 1y={last.sharpe_1y:.2f}")


if __name__ == "__main__":
    main()
