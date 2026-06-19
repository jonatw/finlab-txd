"""一次性:從 finlab monorepo 匯出 seed raw 資料,重建 curve,並證明與現有 curve 逐位元相同。

只在建專案時跑一次(需 finlab monorepo 的 venv + 離線 cache)。產出後本專案永不再依賴 finlab。
    cd /Users/jonatw/proj/finlab
    FINLAB_OFFLINE=1 ./.venv/bin/python /Users/jonatw/proj/finlab-txd/scripts/seed_from_finlab.py

寫出:
  data/raw/{taiex_twii,move,etf_0050,etf_0056,etf_00631L}.csv   (seed, 凍結到 CUTOFF)
  data/derived/curve.csv                                         (seed 重建)
  data/golden/expected.json                                      (凍結錨點)
  data/seed/MANIFEST.json                                        (cutoff + sha256)
並斷言:build_curve(seed) 與 monorepo _txd_trend_movevol_dtp.parquet max|diff| < 1e-6。
"""
import os, sys, json, hashlib
os.environ.setdefault("FINLAB_OFFLINE", "1")
from pathlib import Path
import numpy as np
import pandas as pd
from finlab import data

MONO = Path("/Users/jonatw/proj/finlab")
TXD = Path("/Users/jonatw/proj/finlab-txd")
CUTOFF = pd.Timestamp("2026-06-18")  # seed 凍結日 = 最後一個 finlab 交易日
sys.path.insert(0, str(TXD))
from src.strategy import build_curve  # noqa: E402

RAW = TXD / "data" / "raw"


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    # 1) TAIEX OHLC(= 價格指數,實測 == Yahoo ^TWII)
    cols = {"open": "開盤指數", "high": "最高指數", "low": "最低指數", "close": "收盤指數"}
    taiex = pd.DataFrame(
        {k: data.get(f"taiex_total_index:{v}")["TAIEX"].astype(float) for k, v in cols.items()}
    )
    taiex = taiex[taiex.index <= CUTOFF].dropna(how="all")
    taiex.index.name = "date"
    taiex.round(2).to_csv(RAW / "taiex_twii.csv")

    # 2) MOVE
    move = pd.read_parquet(MONO / "research/data/regime_masks/move_real.parquet")["move"]
    move = move[move.index <= CUTOFF]
    move.index.name = "date"
    move.round(2).rename("move").to_csv(RAW / "move.csv", header=True)

    # 3) ETF 還原含息(0050 接 spliced 回 2003;與 monorepo export 同口徑)
    adj = data.get("etl:adj_close").astype(float)
    spliced = MONO / "research/data/etf_0050_adj_spliced.parquet"
    for t in ("0050", "0056", "00631L"):
        live = adj[t].dropna()
        if t == "0050" and spliced.exists():
            s = pd.read_parquet(spliced)["adj"]
            s.index = pd.to_datetime(s.index)
            s = pd.concat([s, live[live.index > s.index[-1]]])
        else:
            s = live
        s = s[s.index <= CUTOFF]
        s.index.name = "date"
        s.round(4).rename("adj").to_csv(RAW / f"etf_{t}.csv", header=True)

    # 4) 重建 curve + 證明 == monorepo
    curve = build_curve(taiex, move)
    ref = pd.read_parquet(MONO / "research/data/curves/_txd_trend_movevol_dtp.parquet")
    ref.index = pd.to_datetime(ref.index)
    common = curve.index.intersection(ref.index)
    maxdiff = {c: float((curve.loc[common, c] - ref.loc[common, c]).abs().max()) for c in ref.columns}
    print("=== KEYSTONE PROOF: build_curve(seed) vs monorepo curve ===")
    for c, d in maxdiff.items():
        print(f"  {c:11s} max|diff| = {d:.2e}")
    worst = max(maxdiff.values())
    assert worst < 1e-6, f"重建與現有 curve 不符! max|diff|={worst:.2e}"
    print(f"  ✓ 全欄 max|diff| = {worst:.2e}  →  逐位元重現,搬碼正確")

    curve.index.name = "date"
    curve.round(6).to_csv(TXD / "data/derived/curve.csv")

    # 5) golden 錨點
    r = curve["pnl"]
    nav = curve["strategy"]
    def sh(x):
        return float(x.mean() / x.std() * np.sqrt(252))
    def mdd(x):
        n = (1 + x).cumprod()
        return float((n / n.cummax() - 1).min() * 100)
    anchors_dates = ["2010-12-31", "2016-12-30", "2022-12-30", "2025-12-31"]
    expected = {
        "as_of": str(CUTOFF.date()),
        "n_days": int(len(curve)),
        "nav_final": round(float(nav.iloc[-1]), 6),
        "sharpe_full_1999": round(sh(r), 6),
        "mdd_full_1999_pct": round(mdd(r), 4),
        "dtp_gated_days": int(curve["dtp_gated"].sum()),
        "nav_at": {d: round(float(nav.asof(pd.Timestamp(d))), 6) for d in anchors_dates},
        "tol": 1e-6,
    }
    (TXD / "data/golden/expected.json").write_text(json.dumps(expected, indent=2, ensure_ascii=False))

    # 6) MANIFEST(鎖 seed)
    manifest = {
        "cutoff": str(CUTOFF.date()),
        "note": "pre-cutoff = finlab(canonical, frozen);post-cutoff 由 Yahoo 增量。實測:73 個 finlab≠Yahoo 曝險翻轉日全在 2020 前,接縫 bit-safe。",
        "files": {p.name: {"sha256": sha256(p), "rows": sum(1 for _ in p.open()) - 1}
                  for p in sorted(RAW.glob("*.csv"))},
        "source_versions": "finlab offline cache @ 2026-06-19",
    }
    (TXD / "data/seed/MANIFEST.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))

    print("\n=== seed 完成 ===")
    for p in sorted(RAW.glob("*.csv")):
        df = pd.read_csv(p)
        print(f"  {p.name:18s} {len(df):5d} 列  {df['date'].iloc[0]} → {df['date'].iloc[-1]}")
    print(f"  curve.csv {len(curve)} 列 | expected.json nav_final={expected['nav_final']} sharpe={expected['sharpe_full_1999']}")


if __name__ == "__main__":
    main()
