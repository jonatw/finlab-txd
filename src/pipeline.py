"""每日管線:fetch(Yahoo 增量)→ rebuild → metrics → health → export → feed。finlab-free。
    python -m src.pipeline            # 完整跑
    python -m src.pipeline --no-fetch # 只重算(離線/CI 重現)
"""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd
from src import fetch, crosscheck, metrics, export, health, feed, pcr
from src.strategy import build_curve

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
CURVE = ROOT / "data" / "derived" / "curve.csv"


def rebuild_curve() -> pd.DataFrame:
    tx = pd.read_csv(RAW / "taiex_twii.csv", parse_dates=["date"]).set_index("date")
    mv = pd.read_csv(RAW / "move.csv", parse_dates=["date"]).set_index("date")["move"]
    curve = build_curve(tx, mv)
    curve.index.name = "date"
    curve.round(6).to_csv(CURVE)
    return curve


def main(do_fetch: bool = True):
    if do_fetch:
        print("[1/7] fetch (Yahoo incremental)")
        for line in fetch.main():
            print("   ", line)
        print("[2/7] crosscheck (TWSE 官方多源驗證:TAIEX 自動修正 / ETF flag)")
        xc = crosscheck.run()
        if xc.get("skipped"):
            print(f"    skipped (TWSE 不可達): {str(xc.get('error',''))[:60]} — 不擋管線")
        else:
            print(f"    validated; TAIEX 修正 {len(xc['taiex_corrections'])} / ETF 含息修正 {len(xc['etf_corrections'])} / ETF flag {len(xc['etf_flags'])} / 除息 {len(xc['etf_exdiv'])}")
            for c in xc["taiex_corrections"]:
                print(f"      ⚠️ TAIEX {c['date']} 自動修正 {c['old_close']}→{c['new_close']}(Yahoo {c['yahoo_ret_pct']}% vs TWSE {c['twse_ret_pct']}%)")
            for c in xc["etf_corrections"]:
                print(f"      ⚠️ ETF {c['etf']} 含息自動修正 自 {c['from']}({c['n_bars']} bars)末值 {c['old_last_close']}→{c['new_last_close']}")
            for f in xc["etf_flags"]:
                print(f"      ⚠️ ETF {f['etf']} {f['date']} flag(stored {f['stored_ret_pct']}% vs TWSE raw {f.get('twse_raw_ret_pct')}%,股利抓取失敗)→ 人工 review")
    else:
        print("[1/7] fetch skipped (--no-fetch)")
        print("[2/7] crosscheck skipped (--no-fetch;離線重現不打 TWSE)")
    print("[3/7] rebuild curve")
    cv = rebuild_curve()
    print(f"    curve {len(cv)} 列 → {cv.index[-1].date()}")
    print("[4/7] metrics")
    metrics.main()
    print("[5/7] health (paper-lane band + DD breaker)")
    health.main()
    print("[6/7] export JSON")
    export.main()
    print("[7/7] feed (JSON Feed)")
    feed.main()
    # P/C 反向擇時 paper-lane(#133):平行觀察訊號,失敗絕不擋 TXD 主管線
    print("[+] pcr paper-lane (TAIFEX P/C, 平行訊號)")
    try:
        pcr.main(do_fetch=do_fetch)
    except Exception as e:  # noqa: BLE001
        print(f"    pcr: SKIP {str(e)[:60]} (paper-lane 失敗不擋主線)")
    print("✓ pipeline done")


if __name__ == "__main__":
    main(do_fetch="--no-fetch" not in sys.argv)
