"""curve.csv → site/data/health.json:paper-lane 健康監控。

兩塊(回答「策略是不是還有用」,比 Sharpe-over-time 直接):
 A. 實單 vs 期望帶:對策略歷史日報酬做 block-bootstrap(21日塊),產 1 年累積報酬的 5–95% 帶,
    把 deploy 後的真實 NAV 疊上去 —— 掉到 p5 之下 = 低於回測預期(decay 證據)。
 B. DD 斷路器:當前回撤 vs 歷史 MDD(2016+/全期)+ bootstrap 5% 尾 —— 破歷史 MDD = 真正的早期警報。

確定性(seed 固定);每日重算,band 幾乎不動、live 每天長一格。
誠實:期望帶假設報酬分布不變(stationary);paper-lane 初期資料少 = 無統計檢力,面板先把警戒線畫好等資料長。
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
from src.config import PAPER_DEPLOY_DATE

ROOT = Path(__file__).resolve().parents[1]
CURVE = ROOT / "data" / "derived" / "curve.csv"
OUT = ROOT / "site" / "data" / "health.json"
HORIZON, NBOOT, BLOCK, SEED = 252, 2000, 21, 42


def block_bootstrap_paths(r: np.ndarray, horizon: int, nboot: int, block: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = len(r)
    nblocks = horizon // block + 1
    starts = rng.integers(0, n - block, size=(nboot, nblocks))
    paths = np.empty((nboot, horizon))
    for i in range(nboot):
        seg = np.concatenate([r[s:s + block] for s in starts[i]])[:horizon]
        paths[i] = np.cumprod(1.0 + seg)
    return paths


def main():
    cv = pd.read_csv(CURVE, parse_dates=["date"]).set_index("date")
    pnl = cv["pnl"].astype(float).values
    nav = cv["strategy"].astype(float)
    deploy = pd.Timestamp(PAPER_DEPLOY_DATE)

    paths = block_bootstrap_paths(pnl, HORIZON, NBOOT, BLOCK, SEED)
    pct = np.percentile(paths, [5, 25, 50, 75, 95], axis=0)

    live = nav[nav.index >= deploy]
    live = (live / live.iloc[0]) if len(live) else live

    dd = nav / nav.cummax() - 1
    nav16 = nav[nav.index >= "2016-11-01"]
    dd16 = nav16 / nav16.cummax() - 1
    boot_mdd = (paths / np.maximum.accumulate(paths, axis=1) - 1).min(axis=1)

    health = {
        "updated": str(cv.index[-1].date()),
        "deploy_date": str(deploy.date()),
        "horizon": HORIZON,
        "p5": [round(float(x), 4) for x in pct[0]],
        "p25": [round(float(x), 4) for x in pct[1]],
        "p50": [round(float(x), 4) for x in pct[2]],
        "p75": [round(float(x), 4) for x in pct[3]],
        "p95": [round(float(x), 4) for x in pct[4]],
        "live_nav": [round(float(x), 4) for x in live.values],
        "live_dates": [str(d.date()) for d in live.index],
        "dd": {
            "current_pct": round(float(dd.iloc[-1] * 100), 2),
            "mdd_2016_pct": round(float(dd16.min() * 100), 2),
            "mdd_full_pct": round(float(dd.min() * 100), 2),
            "tail_mdd_pct": round(float(np.percentile(boot_mdd, 5) * 100), 2),
        },
        "note": "期望帶 = 策略歷史日報酬 block-bootstrap(21日塊×2000)的 1 年累積分布;假設分布不變。實單掉到 p5 下 = 低於回測預期。paper-lane 初期資料少、無統計檢力。",
    }
    OUT.write_text(json.dumps(health, ensure_ascii=False, separators=(",", ":")))
    d = health["dd"]
    print(f"✓ health.json: deploy {health['deploy_date']} | live {len(live)} 天 | "
          f"DD now {d['current_pct']}% (2016 MDD {d['mdd_2016_pct']}%, full {d['mdd_full_pct']}%, tail {d['tail_mdd_pct']}%)")


if __name__ == "__main__":
    main()
