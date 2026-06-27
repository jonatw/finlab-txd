"""多來源交叉驗證:Yahoo(主)vs TWSE 官方(權威第二來源)。finlab-free。

❓「含息只有 finlab 有,其他源只有原始價,怎麼比?」
  → 含息報酬 = 原始價報酬 + 配息。價格用 TWSE 權威原始價(STOCK_DAY / 指數);配息金額是「公告值」
    不受盤中壞 bar 影響 → 股票配息可用 TWSE TWT49U,**ETF 收益分配不在 TWT49U(那是上市公司
    股票除權息表)→ 改用 yfinance .dividends**(實測 0050/0056 配息齊全)。兩者重建含息,**不需 finlab**。
    多數日無配息 → raw報酬=含息報酬可直接比;配息日加回配息率還原 → 不誤報。

驗證策略:
  - TAIEX(^TWII;指數無除息、TWSE=同一發行量加權指數):不一致 → TWSE 權威,**自動覆寫修正**
    (策略唯一價格輸入,最重要;指數無除息所以安全)。
  - ETF(含息還原對照線):重建含息報酬 = TWSE raw報酬 + yfinance 配息 → 與 stored 不一致則
      **自動修正含息 level**(從第一個壞 bar 沿正確前值用重建報酬重算,= 6/23 手動修的自動版)。
      僅當「配息抓取失敗無法確認還原」時退回 **flag**(避免誤剝配息),交人工 review。
  - TWSE 不可達/格式變 → graceful skipped=True,**絕不擋管線**(同 fetch 失敗哲學)。
  - MOVE(美債波動)無 TW 第二來源 → 維持單源 + 既有掛鐘新鮮度 guard。

結果寫 data/derived/xcheck.json,由 export 併入 signal.json freshness、CI guard 讀取。
"""
from __future__ import annotations
import json
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
DERIVED = ROOT / "data" / "derived"
XCHECK = DERIVED / "xcheck.json"
SETTLE_DAYS = 5
RET_TOL = 0.004        # 報酬差 >0.4pp 視為不一致(>1 tick 的真實偏離)
TWSE = "https://www.twse.com.tw"
ETFS = ("0050", "0056", "00631L")


def _get(path: str, params: dict) -> dict:
    import requests
    r = requests.get(TWSE + path, params={**params, "response": "json"},
                     headers={"User-Agent": "Mozilla/5.0"}, timeout=25)
    j = r.json()
    if j.get("stat") not in ("OK", None):
        raise RuntimeError(f"TWSE {path} stat={j.get('stat')}")
    return j


def _twdate(s: str) -> pd.Timestamp:
    """TWSE 民國日期 → Timestamp。容『115/06/23』『115年06月23日』『1150623』。"""
    s = str(s).replace("年", "/").replace("月", "/").replace("日", "").strip()
    if "/" in s:
        y, m, d = s.split("/")
    else:
        y, m, d = s[:-4], s[-4:-2], s[-2:]
    return pd.Timestamp(int(y) + 1911, int(m), int(d))


def _months(last: pd.Timestamp) -> list[str]:
    """涵蓋 settling 窗的月份(跨月時補前一月)。"""
    return sorted({last.strftime("%Y%m"), (last - pd.Timedelta(days=12)).strftime("%Y%m")})


def twse_taiex(last: pd.Timestamp) -> pd.DataFrame:
    rows = {}
    for ym in _months(last):
        for d in _get("/indicesReport/MI_5MINS_HIST", {"date": ym + "01"}).get("data", []):
            rows[_twdate(d[0])] = [float(x.replace(",", "")) for x in d[1:5]]
    return pd.DataFrame(rows, index=["open", "high", "low", "close"]).T.sort_index()


def twse_close(no: str, last: pd.Timestamp) -> pd.Series:
    out = {}
    for ym in _months(last):
        for d in _get("/exchangeReport/STOCK_DAY", {"date": ym + "01", "stockNo": no}).get("data", []):
            out[_twdate(d[0])] = float(d[6].replace(",", ""))
    return pd.Series(out).sort_index()


def etf_distributions(no: str) -> tuple[dict, bool]:
    """ETF 收益分配 {date: amount}, ok。用 yfinance —— ⚠️ ETF 配息「不在」TWSE TWT49U(那是
    上市公司股票除權息表);yfinance .dividends 才有 ETF 收益分配(實測 0050/0056 2026 配息齊全)。
    配息金額是「公告值」不受盤中捕捉壞 bar 影響 → 配 TWSE 權威原始價 = 可信含息重建。
    ok=False(抓取失敗)→ 呼叫端不自動改 ETF(無法確認配息,避免誤剝),改 flag。"""
    try:
        import yfinance as yf
        s = yf.Ticker(f"{no}.TW").dividends
        if s is None or len(s) == 0:
            return {}, True  # 抓到了、只是無配息(空)→ ok
        return {pd.Timestamp(d.date()): float(v) for d, v in s.items()}, True
    except Exception:
        return {}, False


def run() -> dict:
    """跑交叉驗證:自動修正 TAIEX、flag ETF、寫 xcheck.json。回 report dict。"""
    rep = {"validated": False, "skipped": False,
           "taiex_corrections": [], "etf_corrections": [], "etf_flags": [], "etf_exdiv": []}
    try:
        tx = pd.read_csv(RAW / "taiex_twii.csv", parse_dates=["date"]).set_index("date")
        last = tx.index[-1]
        # --- TAIEX:不一致 → TWSE 權威自動覆寫 ---
        tw_tx = twse_taiex(last)
        sret, tret = tx["close"].pct_change(), tw_tx["close"].reindex(tx.index).pct_change()
        changed = False
        for d in tx.index[-SETTLE_DAYS:]:
            if d in tw_tx.index and pd.notna(sret.get(d)) and pd.notna(tret.get(d)) \
                    and abs(sret[d] - tret[d]) > RET_TOL:
                old = float(tx.loc[d, "close"])
                tx.loc[d, ["open", "high", "low", "close"]] = tw_tx.loc[d, ["open", "high", "low", "close"]].values
                rep["taiex_corrections"].append(
                    {"date": str(d.date()), "old_close": round(old, 2),
                     "new_close": round(float(tw_tx.loc[d, "close"]), 2),
                     "yahoo_ret_pct": round(sret[d] * 100, 2), "twse_ret_pct": round(tret[d] * 100, 2)})
                changed = True
        if changed:
            tx.round(2).to_csv(RAW / "taiex_twii.csv")
        # --- ETF:重建含息報酬(TWSE raw + yfinance 配息)→ 不符則自動修正含息 level;配息抓取失敗才 flag ---
        for no in ETFS:
            path = RAW / f"etf_{no}.csv"
            st = pd.read_csv(path, parse_dates=["date"]).set_index("date")
            adj = st["adj"].astype(float)
            tc = twse_close(no, last)
            raw_ret, prev_c = tc.reindex(adj.index).pct_change(), tc.reindex(adj.index).shift(1)
            divmap, divs_ok = etf_distributions(no)      # ETF 配息(yfinance;TWT49U 不含 ETF)
            recon = raw_ret.copy()                       # 重建含息報酬 = raw報酬 + 配息率(配息日才加)
            for d in adj.index[-SETTLE_DAYS:]:
                dv = divmap.get(pd.Timestamp(d.date()))
                if dv and pd.notna(prev_c.get(d)) and prev_c[d]:
                    recon[d] = raw_ret[d] + dv / float(prev_c[d])
                    rep["etf_exdiv"].append({"etf": no, "date": str(d.date()), "div": dv})
            sret = adj.pct_change()
            bad = [d for d in adj.index[-SETTLE_DAYS:] if d in tc.index and pd.notna(sret.get(d))
                   and pd.notna(recon.get(d)) and abs(sret[d] - recon[d]) > RET_TOL]
            if not bad:
                continue
            if not divs_ok:                              # 無法確認股利 → 不自動改(避免誤剝股利),只 flag
                for d in bad:
                    rep["etf_flags"].append({"etf": no, "date": str(d.date()),
                        "stored_ret_pct": round(sret[d] * 100, 2), "twse_raw_ret_pct": round(raw_ret[d] * 100, 2),
                        "note": "stored含息 vs TWSE 不符,但股利抓取失敗無法還原 → 人工 review"})
                continue
            # 自動修正:從第一個壞 bar 起,沿正確前值用「重建含息報酬」重算 level(校正 level 位移)
            # ⚠️ 已知限度(display-only):若 yfinance 在某除息日「靜默漏掉」配息,recon 會少加配息 →
            #    可能把正確含息 bar 判壞並修掉配息。display-only(不餵策略)、下次抓到即自癒;故不擋。
            p0 = adj.index.get_loc(bad[0]); rng = adj.index[p0:]
            if any((d not in tc.index or pd.isna(recon.get(d))) for d in rng):  # 重建窗內 TWSE 有缺 → 不部分重建(免留 kink),改 flag
                for d in bad:
                    rep["etf_flags"].append({"etf": no, "date": str(d.date()),
                        "stored_ret_pct": round(sret[d] * 100, 2), "twse_raw_ret_pct": round(raw_ret[d] * 100, 2),
                        "note": "重建窗內 TWSE 有缺日,不部分重建 → 人工 review"})
                continue
            old_last = round(float(adj.iloc[-1]), 4); cur = float(adj.iloc[p0 - 1])
            for d in rng:
                cur *= (1 + recon[d]); adj.loc[d] = round(cur, 4)
            st["adj"] = adj; st.round(4).to_csv(path)
            rep["etf_corrections"].append({"etf": no, "from": str(bad[0].date()), "n_bars": len(rng),
                "old_last_close": old_last, "new_last_close": round(float(adj.iloc[-1]), 4)})
        rep["validated"] = True
    except Exception as e:  # noqa: BLE001 — 保留已累積的修正記錄(別讓後段例外抹掉前段已寫檔的 audit trail)
        rep["skipped"] = True
        rep["error"] = str(e)[:140]
    rep["mismatch"] = bool(rep["etf_flags"])
    DERIVED.mkdir(parents=True, exist_ok=True)
    XCHECK.write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    return rep


if __name__ == "__main__":
    r = run()
    print(f"xcheck: validated={r['validated']} skipped={r['skipped']} "
          f"taiex_fixed={len(r['taiex_corrections'])} etf_fixed={len(r['etf_corrections'])} "
          f"etf_flags={len(r['etf_flags'])} etf_exdiv={len(r['etf_exdiv'])}")
    for c in r["taiex_corrections"]:
        print(f"  TAIEX 修正 {c['date']}: {c['old_close']}→{c['new_close']} (Yahoo {c['yahoo_ret_pct']}% vs TWSE {c['twse_ret_pct']}%)")
    for c in r["etf_corrections"]:
        print(f"  ETF 含息修正 {c['etf']} 自 {c['from']}({c['n_bars']} bars): 末值 {c['old_last_close']}→{c['new_last_close']}")
    for f in r["etf_flags"]:
        print(f"  ⚠️ ETF flag {f['etf']} {f['date']}: stored {f['stored_ret_pct']}% vs TWSE raw {f.get('twse_raw_ret_pct')}% (股利抓取失敗)")
