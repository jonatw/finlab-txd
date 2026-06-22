"""每日增量抓 Yahoo,append 進 data/raw/*.csv。finlab-free、冪等、有壞 tick 防呆。

來源(實測對齊 finlab,見 README):TAIEX=^TWII OHLC、MOVE=^MOVE、ETF=*.TW 還原含息。
- append-only by date:只抓 csv 最後日期之後的 bar,去重。
- seed(cutoff 之前)永不覆寫:只 append 新日。
- 壞 tick gate:high≥close/open≥low、單日 |漲跌|<11%、正值有限 → 不過則拒收該 bar。
- ETF 用 overlap 重算 scale 接縫(finlab 錨點 ≠ Yahoo 錨點,但 return 相同 → 縮放接續)。
- 任一來源失敗 → 保留現有資料 + 回報 warning,不丟例外(管線不崩)。
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

RAW = Path(__file__).resolve().parents[1] / "data" / "raw"
MAX_DAILY_MOVE = 0.11  # 台股 ±10% + buffer


def _yf(symbol: str, auto_adjust: bool, period: str = "1y", tries: int = 4) -> pd.DataFrame:
    """抓 Yahoo,對暫時性失敗做 backoff 重試(yfinance 失敗常為 rate-limit / 端點抖動)。
    健康的 1y 下載必非空 → 回空集合視同失敗重試(區分『Yahoo 掛了』與『沒有新 bar』)。
    最終仍失敗 → raise,交給上層 main() 的 try/except『keep existing + warning』。"""
    import time
    import yfinance as yf
    last = None
    for i in range(tries):
        try:
            df = yf.download(symbol, period=period, progress=False, auto_adjust=auto_adjust)
            if not df.empty:
                if df.columns.nlevels > 1:
                    df.columns = df.columns.get_level_values(0)
                df.index = pd.to_datetime(df.index)
                return df
            last = "empty result (Yahoo 可能擋下/壞掉)"
        except Exception as e:  # noqa: BLE001
            last = str(e)[:80]
        if i < tries - 1:
            time.sleep(3 * (i + 1))  # 3 / 6 / 9 秒 backoff
    raise RuntimeError(f"yfinance {symbol} failed after {tries} tries: {last}")


def _read(name: str) -> pd.DataFrame:
    df = pd.read_csv(RAW / name, parse_dates=["date"]).set_index("date")
    return df


def update_taiex() -> str:
    df = _read("taiex_twii.csv")
    last = df.index[-1]
    y = _yf("^TWII", auto_adjust=False)
    new = y[y.index > last][["Open", "High", "Low", "Close"]].dropna()
    new.columns = ["open", "high", "low", "close"]
    kept, prev_close = [], float(df["close"].iloc[-1])
    for d, row in new.iterrows():
        o, h, l, c = float(row.open), float(row.high), float(row.low), float(row.close)
        ok = (h >= l > 0) and (h >= c >= l) and (h >= o >= l) and all(np.isfinite([o, h, l, c]))
        ok = ok and abs(c / prev_close - 1) < MAX_DAILY_MOVE
        if ok:
            kept.append((d, o, h, l, c)); prev_close = c
    if not kept:
        return f"taiex: 0 new (last {last.date()})"
    add = pd.DataFrame(kept, columns=["date", "open", "high", "low", "close"]).set_index("date")
    out = pd.concat([df, add]).round(2)
    out = out[~out.index.duplicated(keep="last")].sort_index()
    out.to_csv(RAW / "taiex_twii.csv")
    return f"taiex: +{len(add)} → {out.index[-1].date()}"


def update_move() -> str:
    df = _read("move.csv")
    last = df.index[-1]
    y = _yf("^MOVE", auto_adjust=True)
    new = y[y.index > last]["Close"].dropna()
    kept = [(d, float(v)) for d, v in new.items() if np.isfinite(v) and v > 0 and abs(v / float(df["move"].iloc[-1]) - 1) < 0.5]
    if not kept:
        return f"move: 0 new (last {last.date()})"
    add = pd.DataFrame(kept, columns=["date", "move"]).set_index("date")
    out = pd.concat([df, add]).round(2)
    out = out[~out.index.duplicated(keep="last")].sort_index()
    out.to_csv(RAW / "move.csv")
    return f"move: +{len(add)} → {out.index[-1].date()}"


def update_etf(ticker: str) -> str:
    fn = f"etf_{ticker}.csv"
    df = _read(fn)
    last = df.index[-1]
    y = _yf(f"{ticker}.TW", auto_adjust=True)["Close"].dropna()
    if y.empty:
        return f"{ticker}: yahoo empty"
    # overlap 重算 scale(finlab 錨點 ≠ Yahoo;return 相同 → 縮放接續)
    overlap = df.index.intersection(y.index)
    if overlap.empty:
        return f"{ticker}: no overlap, skip (manual reseam needed)"
    od = overlap[-1]
    scale = float(df.loc[od, "adj"]) / float(y.loc[od])
    new = y[y.index > last]
    kept = [(d, round(float(v) * scale, 4)) for d, v in new.items() if np.isfinite(v) and v > 0]
    if not kept:
        return f"{ticker}: 0 new (last {last.date()})"
    add = pd.DataFrame(kept, columns=["date", "adj"]).set_index("date")
    out = pd.concat([df, add])
    out = out[~out.index.duplicated(keep="last")].sort_index()
    out.to_csv(RAW / fn)
    return f"{ticker}: +{len(add)} → {out.index[-1].date()}"


def main() -> list[str]:
    log = []
    for fn, label in [(update_taiex, "taiex"), (update_move, "move")]:
        try:
            log.append(fn())
        except Exception as e:  # noqa: BLE001
            log.append(f"{label}: FAIL {str(e)[:60]} (keep existing)")
    for t in ("0050", "0056", "00631L"):
        try:
            log.append(update_etf(t))
        except Exception as e:  # noqa: BLE001
            log.append(f"{t}: FAIL {str(e)[:60]} (keep existing)")
    return log


if __name__ == "__main__":
    for line in main():
        print(" ", line)
