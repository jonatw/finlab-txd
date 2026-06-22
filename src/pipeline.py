"""每日管線:fetch(Yahoo 增量)→ rebuild → metrics → health → export → feed。finlab-free。
    python -m src.pipeline            # 完整跑
    python -m src.pipeline --no-fetch # 只重算(離線/CI 重現)
"""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd
from src import fetch, metrics, export, health, feed, pcr
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
        print("[1/6] fetch (Yahoo incremental)")
        for line in fetch.main():
            print("   ", line)
    else:
        print("[1/6] fetch skipped (--no-fetch)")
    print("[2/6] rebuild curve")
    cv = rebuild_curve()
    print(f"    curve {len(cv)} 列 → {cv.index[-1].date()}")
    print("[3/6] metrics")
    metrics.main()
    print("[4/6] health (paper-lane band + DD breaker)")
    health.main()
    print("[5/6] export JSON")
    export.main()
    print("[6/6] feed (JSON Feed)")
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
