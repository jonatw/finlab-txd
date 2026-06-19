"""curve.csv + raw → site/data/{signal,nav}.json(餵 index.html)。finlab-free port。

結構與 monorepo export_txd_dashboard.py 一致,讓既有 index.html 不改即可用。
唯讀資料,只寫 JSON。
"""
from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
import numpy as np
import pandas as pd
from src.strategy import ATR_WIN, DTP_LOOKBACK, DTP_THRESH

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "site" / "data"
CURVE = ROOT / "data" / "derived" / "curve.csv"
POS_TXT = {0: "空手 / 平倉", 1: "台指期 1x 做多", 2: "台指期 2x 做多"}


def _series(name, col="adj"):
    df = pd.read_csv(RAW / name, parse_dates=["date"]).set_index("date")
    return df[col].astype(float)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cv = pd.read_csv(CURVE, parse_dates=["date"]).set_index("date")
    ref = cv.index[-1]
    tx = pd.read_csv(RAW / "taiex_twii.csv", parse_dates=["date"]).set_index("date")
    idx, hi, lo = tx["close"].dropna().astype(float), tx["high"].astype(float), tx["low"].astype(float)
    cal = idx.index
    market_latest = idx.index[-1]
    curve_stale = bool(market_latest > ref)

    ma = {w: idx.rolling(w).mean() for w in (60, 120, 200)}
    above = {w: bool(idx.loc[ref] > ma[w].loc[ref]) for w in (60, 120, 200)}
    spine_now = sum(above.values()) / 3.0

    move_df = pd.read_csv(RAW / "move.csv", parse_dates=["date"]).set_index("date")
    move = move_df["move"].reindex(cal, method="ffill")
    med = move.rolling(252, min_periods=120).quantile(0.5)
    move_low = bool(move.loc[ref] < med.loc[ref])

    tr = pd.concat([hi - lo, (hi - idx.shift(1)).abs(), (lo - idx.shift(1)).abs()], axis=1).max(axis=1)
    atr_pct = tr.ewm(alpha=1 / ATR_WIN, adjust=False).mean() / idx * 100
    dtp = atr_pct.rolling(DTP_LOOKBACK).apply(lambda x: (x.iloc[-1] >= x).mean(), raw=False)
    dtp_ref = float(dtp.loc[ref]) if pd.notna(dtp.loc[ref]) else 0.0
    gated_next = bool(dtp_ref >= DTP_THRESH)

    move_as_of = min(pd.Timestamp(move_df.index[-1]), ref)
    move_lag = max(int(np.busday_count(pd.Timestamp(move_df.index[-1]).date(), ref.date())), 0)
    for_session = ref + pd.offsets.BDay(1)
    exp_sig = cv["exposure"]
    exp_held = exp_sig.shift(1).fillna(0.0)
    target = 0.0 if gated_next else float(exp_sig.iloc[-1])
    prev = float(exp_sig.iloc[-2])
    changed = abs(target - prev) > 1e-9
    action = "不需調倉" if not changed else ("加碼" if target > prev else "減碼")

    signal = {
        "px_as_of": str(ref.date()), "move_as_of": str(move_as_of.date()),
        "for_session": str(for_session.date()), "for_session_approx": True,
        "target_exposure": round(target, 2), "prev_exposure": round(prev, 2),
        "changed": changed, "action": action,
        "pos_text": ("🚨 高波動關機 / 空手" if gated_next else POS_TXT.get(round(target), f"{target:.2f}x 做多")),
        "spine": {"value": round(spine_now, 2), "index_close": round(float(idx.loc[ref]), 2),
                  "ma": {str(w): round(float(ma[w].loc[ref]), 2) for w in (60, 120, 200)},
                  "above_ma": [w for w in (60, 120, 200) if above[w]], "n_above": sum(above.values())},
        "move": {"value": round(float(move.loc[ref]), 1), "median252": round(float(med.loc[ref]), 1),
                 "regime": "低波加碼" if move_low else "常波", "mult": 2 if move_low else 1},
        "dtp": {"percentile": round(dtp_ref * 100, 1), "atr_pct": round(float(atr_pct.loc[ref]), 2),
                "threshold_pct": int((1 - DTP_THRESH) * 100), "gated_next": gated_next,
                "regime": "🚨 市場發瘋(關機)" if gated_next else ("偏高波動" if dtp_ref >= 0.85 else "正常"),
                "note": f"DTP% = ATR({ATR_WIN})% 佔收盤的 {DTP_LOOKBACK} 日百分位; ≥ top-{int((1-DTP_THRESH)*100)}% = 發瘋日, 次一交易日空手"},
        "status": {"stage": "RESEARCH", "lane_health": "VALIDATED", "deploy_date": None,
                   "note": "TXD = TX + DTP 濾網, 已過 look-ahead + overfit 兩道稽核。live 期望 Sharpe ~1.35"},
        "freshness": {"px_index": str(ref.date()), "move": str(move_as_of.date()),
                      "curve_stale": curve_stale, "market_latest": str(market_latest.date()),
                      "move_lag_bdays": move_lag, "stale_warn": bool(move_lag > 1 or curve_stale),
                      "note": "MOVE 是美債波動, 正常晚台股 1 個交易日; curve_stale=true 表示策略 curve 還沒重生到最新交易日"},
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }

    def etf(t):
        s = _series(f"etf_{t}.csv").reindex(cv.index)
        return [round(float(x), 4) if pd.notna(x) else None for x in s]

    nav = {
        "updated": str(ref.date()),
        "haircut_note": "TXD(TX+DTP濾網, Wilder ATR)回測全期 Sharpe 1.40 / MDD -20%; live 合理期望 ~1.35-1.40, 別用回測數字外推",
        "benchmark_note": "benchmark = 加權指數(價格指數, 台指期結算標的; 不含股息)",
        "dtp_note": "DTP% 高波動關機: 昨日 ATR%(Wilder) 衝進 250 日 top-4% → 今日空手(避雙巴); 降 MDD -32%→-20%, CAGR 不動",
        "series": {
            "date": [str(d.date()) for d in cv.index],
            "nav": [round(float(x), 4) for x in cv["strategy"]],
            "benchmark": [round(float(x), 4) for x in cv["benchmark"]],
            "exposure_signal": [round(float(x), 2) for x in exp_sig],
            "exposure_held": [round(float(x), 2) for x in exp_held],
            "move_mult": [2 if bool(move.loc[d] < med.loc[d]) else 1 for d in cv.index],
            "dtp_gated": [int(x) for x in cv["dtp_gated"]],
            "etf_0050": etf("0050"), "etf_0056": etf("0056"), "etf_00631L": etf("00631L"),
        },
        "etf_note": "0050/0056/00631L = 還原含息(持有人真實報酬口徑, 與不含息的加權指數基準不同); 上市前無資料不畫",
    }
    (OUT / "signal.json").write_text(json.dumps(signal, ensure_ascii=False, indent=2))
    (OUT / "nav.json").write_text(json.dumps(nav, ensure_ascii=False, separators=(",", ":")))
    print(f"✓ signal.json: {ref.date()} target {target}x DTP {dtp_ref*100:.0f}%{' 🚨' if gated_next else ''}")
    print(f"✓ nav.json: {len(cv)} 天, updated {nav['updated']}, 關機日 {sum(nav['series']['dtp_gated'])}")


if __name__ == "__main__":
    main()
