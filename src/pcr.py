"""TAIFEX 買賣權未平倉量 P/C ratio 反向擇時 — 平行 paper-lane 觀察訊號。

身分:這是**平行於 TXD 的 paper-lane 訊號**(#133),不混入 TXD 的部署曲線。
TXD 自己的 spine×MOVE×DTP 完全不動;P/C 只是另一條獨立追蹤的紙上曲線,
等它在 live 累積 track record 後再決定要不要 blend(研究實測 blend 數字更好,
但部署前要先觀察)。

資料源:TAIFEX 官方 `pcRatioDown` 端點 —— 免費、全歷史、big5 CSV、**不需 token**,
finlab-free / CI-zero-paid-credentials 身分不變(同 Yahoo,純公開端點)。
seed(data/raw/taifex_pcr.csv)由研究 harness 的 16 年 gauntlet-passed 資料凍結,
live 只增量抓最近 ~30 天(單一請求,不觸發 TAIFEX 的 31 天範圍上限/rapid-loop 擋)。

規格(凍結,反向 long/flat):`P/C[D] > 自身 trailing-252 p60` → 隔日做多加權指數;
否則空手。邏輯:低 P/C=散戶自滿→避崩盤;高 P/C=恐慌投降→抄反彈。T+1、2bps/側。
已過 look-ahead(shift load-bearing)+ overfit(CPCV/PBO benign flat-grid)兩道稽核;
研究全期(2010-2026)Sharpe 1.07 / MDD −25 / 躲 5-6 危機,與 TXD 日 PnL corr 0.61。
"""
from __future__ import annotations
import json
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from src.config import PCR_PAPER_DEPLOY_DATE

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
DERIVED = ROOT / "data" / "derived"
OUT = ROOT / "site" / "data"
PCR_CSV = RAW / "taifex_pcr.csv"
PCR_CURVE = DERIVED / "pcr_curve.csv"

TW = ZoneInfo("Asia/Taipei")
TAIFEX_URL = "https://www.taifex.com.tw/cht/3/pcRatioDown"
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# 凍結策略參數(這些不是旋鈕,是研究 gauntlet 過關的定值)
WINDOW = 252        # trailing 視窗
MIN_PERIODS = 126   # window // 2(同研究 gate.py)
PCTILE = 0.60       # p60 門檻
COST_PER_SIDE = 0.0002  # 2bps


# ────────────────────────── 抓取(TAIFEX 免費端點) ──────────────────────────
def _fetch_taifex(start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """抓 [start, end] 的 P/C OI ratio(買賣權未平倉量比率%)。big5 CSV、單一請求。
    回 DataFrame[index=date, pcr];失敗 raise,交上層 main() 的 keep-existing。"""
    data = urllib.parse.urlencode({
        "queryStartDate": start.strftime("%Y/%m/%d"),
        "queryEndDate": end.strftime("%Y/%m/%d"),
    }).encode()
    req = urllib.request.Request(TAIFEX_URL, data=data, headers={"User-Agent": _UA})
    raw = urllib.request.urlopen(req, timeout=30).read()
    txt = raw.decode("big5", errors="replace")
    rows = []
    for ln in txt.splitlines()[1:]:  # skip header
        parts = [p.strip() for p in ln.split(",")]
        if len(parts) < 7 or not parts[0]:
            continue
        try:
            d = pd.Timestamp(parts[0].replace("/", "-"))
            pcr = float(parts[6])  # 買賣權未平倉量比率%
        except (ValueError, TypeError):
            continue
        if np.isfinite(pcr) and pcr > 0:
            rows.append((d, pcr))
    if not rows:
        raise RuntimeError("taifex pcRatio: empty/unparseable result")
    return pd.DataFrame(rows, columns=["date", "pcr"]).set_index("date").sort_index()


def update_pcr() -> str:
    """增量:讀現有 csv → 抓最後日期之後到今天 → append、去重、存。
    只抓最近窗(≤~40 天)避免觸 31 天上限/rapid-loop 擋;seed 之前永不覆寫。"""
    df = pd.read_csv(PCR_CSV, parse_dates=["date"]).set_index("date").sort_index()
    last = df.index[-1]
    today = pd.Timestamp(datetime.now(TW).date())
    if today <= last:
        return f"pcr: 0 new (last {last.date()})"
    start = last + pd.Timedelta(days=1)
    # 單請求覆蓋 [last+1, today];若 gap > 30 天(久未跑),只抓近 30 天(避範圍上限)
    if (today - start).days > 30:
        start = today - pd.Timedelta(days=30)
    new = _fetch_taifex(start, today)
    new = new[new.index > last]
    if new.empty:
        return f"pcr: 0 new (last {last.date()})"
    out = pd.concat([df, new]).round(2)
    out = out[~out.index.duplicated(keep="last")].sort_index()
    out.to_csv(PCR_CSV)
    return f"pcr: +{len(new)} → {out.index[-1].date()}"


# ────────────────────────── 訊號/曲線(凍結邏輯) ──────────────────────────
def build_pcr_curve(taiex_close: pd.Series, pcr: pd.Series) -> pd.DataFrame:
    """凍結反向擇時曲線。回 DataFrame(index=date):
    pcr, threshold(p60), signal(隔日 raw 訊號 1/0), pos(實際持倉=signal.shift1),
    ret(加權指數日報酬), pnl, strategy(NAV), benchmark(buy-hold NAV)。
    時序:pos = signal.shift(1) → 純因果(T+1),由 leakguard 守。"""
    idx = taiex_close.astype(float)
    ret = idx.pct_change().fillna(0.0)
    pc = pcr.reindex(idx.index).astype(float)
    thr = pc.rolling(WINDOW, min_periods=MIN_PERIODS).quantile(PCTILE)
    signal = (pc > thr).astype(float)          # D 收盤後算出的「隔日做多」訊號
    signal[thr.isna() | pc.isna()] = 0.0
    pos = signal.shift(1).fillna(0.0)          # 實際持倉(T+1)
    pnl = pos * ret - pos.diff().abs().fillna(0.0) * COST_PER_SIDE
    out = pd.DataFrame({
        "pcr": pc, "threshold": thr, "signal": signal, "pos": pos,
        "ret": ret, "pnl": pnl,
        "strategy": (1.0 + pnl).cumprod(),
        "benchmark": (1.0 + ret).cumprod(),
    })
    out.index.name = "date"
    return out


def _sharpe(p: pd.Series) -> float:
    p = p.dropna()
    return float(p.mean() / p.std() * np.sqrt(252)) if len(p) > 20 and p.std() > 0 else 0.0


def _mdd(nav: pd.Series) -> float:
    nav = nav.dropna()
    return float((nav / nav.cummax() - 1).min() * 100) if len(nav) else 0.0


# ────────────────────────── 管線 entry ──────────────────────────
def rebuild() -> pd.DataFrame:
    """讀 raw → 建凍結曲線 → 落地 data/derived/pcr_curve.csv。"""
    tx = pd.read_csv(RAW / "taiex_twii.csv", parse_dates=["date"]).set_index("date")
    pcr = pd.read_csv(PCR_CSV, parse_dates=["date"]).set_index("date")["pcr"]
    curve = build_pcr_curve(tx["close"], pcr)
    DERIVED.mkdir(parents=True, exist_ok=True)
    curve.round(6).to_csv(PCR_CURVE)
    return curve


def export(curve: pd.DataFrame, write: bool = True) -> dict:
    """產 site/data/pcr.json:現況訊號 + paper-lane NAV(起算 PCR_PAPER_DEPLOY_DATE)。"""
    cv = curve.dropna(subset=["pcr"])
    ref = cv.index[-1]
    pc_now = float(cv["pcr"].iloc[-1])
    thr_now = float(cv["threshold"].iloc[-1])
    # 現值在 trailing-252 的百分位(自滿↔恐慌的位置感)
    win = cv["pcr"].iloc[-WINDOW:]
    pctile_now = float((win <= pc_now).mean()) if len(win) >= MIN_PERIODS else float("nan")
    sig_next = bool(cv["signal"].iloc[-1] > 0.5)  # D 收盤算出 → 用於 D+1

    # paper-lane:起算日後重設基底 = 1.0(紙上追蹤,對照回測期望)
    dep = pd.Timestamp(PCR_PAPER_DEPLOY_DATE)
    paper = cv[cv.index >= dep]
    paper_nav = float((1.0 + paper["pnl"]).prod()) if len(paper) else 1.0
    paper_bench = float((1.0 + paper["ret"]).prod()) if len(paper) else 1.0

    out = {
        "pcr_as_of": str(ref.date()),
        "pcr_value": round(pc_now, 2),
        "threshold_p60": round(thr_now, 2),
        "trailing_pctile": round(pctile_now * 100, 1) if pctile_now == pctile_now else None,
        "signal_next": sig_next,
        "pos_text": "做多加權指數(P/C 偏高=恐慌→抄反彈)" if sig_next
                    else "空手(P/C 偏低=自滿→避崩盤)",
        "regime": "恐慌/投降區(進場)" if sig_next else "自滿/樂觀區(避開)",
        "rule": f"P/C > 自身 trailing-{WINDOW} p{int(PCTILE*100)} → 隔日做多;否則空手(T+1, 2bps)",
        "backtest": {
            "span": f"{cv.index[0].date()}~{ref.date()}",
            "sharpe": round(_sharpe(cv["pnl"]), 2),
            "mdd_pct": round(_mdd(cv["strategy"]), 1),
            "note": "全期回測參考值;非 live 保證。研究 gauntlet:躲 5-6 危機、PBO benign、與 TXD corr 0.61",
        },
        "paper_lane": {
            "deploy_date": PCR_PAPER_DEPLOY_DATE,
            "days": int(len(paper)),
            "nav": round(paper_nav, 4),
            "benchmark": round(paper_bench, 4),
            "note": "P/C 反向擇時平行 paper-lane(#133)。不混入 TXD 部署曲線;"
                    "養 track record 後再決定 standalone vs 與 TXD blend(研究實測 blend 更好)",
        },
        "generated_at": datetime.now(TW).isoformat(timespec="seconds"),
    }
    if write:
        OUT.mkdir(parents=True, exist_ok=True)
        path = OUT / "pcr.json"
        # 冪等:除 generated_at 外無變化 → 留舊時戳(不刷無謂 commit)
        if path.exists():
            try:
                old = json.loads(path.read_text())
                if {k: v for k, v in old.items() if k != "generated_at"} == \
                   {k: v for k, v in out.items() if k != "generated_at"}:
                    out["generated_at"] = old.get("generated_at", out["generated_at"])
            except Exception:  # noqa: BLE001
                pass
        path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
        print(f"✓ pcr.json: {ref.date()} P/C {pc_now:.1f} (p{out['trailing_pctile']}) "
              f"→ {'做多' if sig_next else '空手'}")
    return out


def main(do_fetch: bool = True) -> dict:
    """P/C paper-lane 一步:fetch(TAIFEX 免費)→ rebuild 凍結曲線 → export pcr.json。
    任何步驟失敗都不該擋 TXD 主管線(paper-lane 是次要觀察)→ 上層 pipeline 包 try。"""
    if do_fetch:
        try:
            print("    ", update_pcr())
        except Exception as e:  # noqa: BLE001
            print(f"     pcr fetch: FAIL {str(e)[:60]} (keep existing)")
    cv = rebuild()
    return export(cv)


if __name__ == "__main__":
    import sys
    main(do_fetch="--no-fetch" not in sys.argv)
