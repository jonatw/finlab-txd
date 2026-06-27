"""每日增量抓 Yahoo,append 進 data/raw/*.csv。finlab-free、冪等、有壞 tick 防呆。

來源(實測對齊 finlab,見 README):TAIEX=^TWII OHLC、MOVE=^MOVE、ETF=*.TW 還原含息。
- settling 窗 + append(**僅指數 ^TWII/^MOVE**):重抓「最近 SETTLE_DAYS 個已存交易日 + 新交易日」,
  允許用 Yahoo 最終值覆寫。更舊的 bar 永不覆寫(保護 seed/history 不被 Yahoo 事後改寫)。
  ↑ 為何不用純 append-only:純 append(只取 index>last)會把「收盤後仍 preliminary 的盤中捕捉」
  永久凍結 —— 實測 2026-06-23 ^TWII 被存成盤中早盤值(漲),隔日不再回看而錯到底。settling 窗
  讓這類 preliminary 捕捉在後續班次自我修復。
- **ETF 例外維持 append-only**:auto_adjust 含息還原會因除息事後回頭重算整段,重抓舊 bar 反而會用
  漂移/壞的當下還原值覆寫正確捕捉(實測 0050 6/22 重抓後 +3.59%→+5.33% 錯掉)。只有無除息調整的
  指數才安全重抓。
- partial today gate:_session_cutoff 擋掉「今天未過 13:30 收盤」的未完成 bar(現貨/ETF)。
- 壞 tick gate:high≥close/open≥low、單日 |漲跌|<11%、正值有限 → 不過則保留現有 bar(不丟歷史)。
- ETF 用 overlap 重算 scale 接縫(finlab 錨點 ≠ Yahoo 錨點,但 return 相同 → 縮放接續)。
- 任一來源失敗 → 保留現有資料 + 回報 warning,不丟例外(管線不崩)。
"""
from __future__ import annotations
from datetime import datetime, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd

RAW = Path(__file__).resolve().parents[1] / "data" / "raw"
MAX_DAILY_MOVE = 0.11  # 台股 ±10% + buffer
SETTLE_DAYS = 5        # 最近 N 個已存交易日重抓覆寫(讓 preliminary/盤中捕捉自我修復);更舊不動
TW = ZoneInfo("Asia/Taipei")
TWSE_CLOSE = dtime(13, 30)  # 台股現貨收盤


def _session_cutoff(now=None) -> pd.Timestamp:
    """可 append 的最後 bar 日期上限:擋掉『今天未過 13:30 收盤』的 partial bar。
    盤前/盤中(< 13:30)→ 上限退回昨天(拒收今天未完成的列);收盤後 → 含今天。
    只 append 已完成的交易日 → 避免 partial bar 把訊號推到隔天、且不會被後續班(> last)漏修。
    holiday 不需精算:這是上限,yfinance 本就不回週末/假日 bar。"""
    now = now or datetime.now(TW)
    if now.tzinfo is None:
        now = now.replace(tzinfo=TW)
    today = pd.Timestamp(now.date())
    return (today - pd.Timedelta(days=1)) if now.time() < TWSE_CLOSE else today


def _yf(symbol: str, auto_adjust: bool, period: str = "1y", tries: int = 4) -> pd.DataFrame:
    """抓 Yahoo,對暫時性失敗做 backoff 重試(yfinance 失敗常為 rate-limit / 端點抖動)。
    健康的 1y 下載必非空 → 回空集合視同失敗重試(區分『Yahoo 掛了』與『沒有新 bar』)。
    最終仍失敗 → raise,交給上層 main() 的 try/except『keep existing + warning』。"""
    import time
    import yfinance as yf
    last = None
    for i in range(tries):
        try:
            # repair=True 是關鍵:Yahoo bulk daily endpoint 會「靜默回傳過期的最近 bar」——
            # 實測 ^MOVE 用 yf.download(無 repair) 只回到 06-18,但實際已到 06-24(網站 4:33pm EDT 即有)。
            # 早上抓不到、下午才補上就是這個 cache 過期。repair=True 觸發 yfinance 完整重抓+修復,
            # 補回被 cache 漏掉的最新交易日(回 tz-naive index,行為與原本一致)。
            # append-only 設計保護:repair 即使改寫舊 bar,我們也只取 index > last 的新列。
            df = yf.download(symbol, period=period, progress=False, auto_adjust=auto_adjust, repair=True)
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
    cutoff = _session_cutoff()  # 只收已收盤的交易日,擋 partial today bar
    # settling 窗:重抓最近 SETTLE_DAYS 個已存交易日 + 新交易日 → 允許覆寫 preliminary 捕捉;更舊不動
    settle_start = df.index[-SETTLE_DAYS] if len(df) > SETTLE_DAYS else df.index[0]
    cand = y[(y.index >= settle_start) & (y.index <= cutoff)][["Open", "High", "Low", "Close"]].dropna()
    cand.columns = ["open", "high", "low", "close"]
    prior = df.index[df.index < settle_start]
    last_good = float(df.loc[prior[-1], "close"]) if len(prior) else (float(cand["close"].iloc[0]) if len(cand) else 0.0)
    kept, gap = [], 1
    for d, row in cand.iterrows():
        o, h, l, c = float(row.open), float(row.high), float(row.low), float(row.close)
        ok = (h >= l > 0) and (h >= c >= l) and (h >= o >= l) and all(np.isfinite([o, h, l, c]))
        ok = ok and abs(c / last_good - 1) < MAX_DAILY_MOVE * gap  # gap>1:前一 bar 被拒→容許跨日 move,免單一壞 bar 連鎖擋掉後續 legit bar
        if ok:
            kept.append((d, o, h, l, c)); last_good = c; gap = 1
        else:
            gap += 1                  # 此 bar 被拒(stored 經 concat keep=last 保留)→ 下一 bar 容許窗 +1 日
    if not kept:
        return f"taiex: 0 new (last {last.date()})"
    add = pd.DataFrame(kept, columns=["date", "open", "high", "low", "close"]).set_index("date")
    out = pd.concat([df, add]).round(2)
    out = out[~out.index.duplicated(keep="last")].sort_index()  # keep=last → 重抓最終值覆寫舊 bar
    out.to_csv(RAW / "taiex_twii.csv")
    n_new = int((add.index > last).sum()); n_fix = len(add) - n_new
    return f"taiex: +{n_new} new, {n_fix} refreshed → {out.index[-1].date()}"


def update_move() -> str:
    df = _read("move.csv")
    last = df.index[-1]
    y = _yf("^MOVE", auto_adjust=True)
    settle_start = df.index[-SETTLE_DAYS] if len(df) > SETTLE_DAYS else df.index[0]
    cand = y[y.index >= settle_start]["Close"].dropna()
    prior = df.index[df.index < settle_start]
    last_good = float(df.loc[prior[-1], "move"]) if len(prior) else float(df["move"].iloc[-1])
    kept, gap = [], 1
    for d, v in cand.items():
        v = float(v)
        if np.isfinite(v) and v > 0 and abs(v / last_good - 1) < 0.5 * gap:  # gap-scaled:免單一壞 bar 連鎖擋掉後續 legit bar
            kept.append((d, v)); last_good = v; gap = 1
        else:
            gap += 1
    if not kept:
        return f"move: 0 new (last {last.date()})"
    add = pd.DataFrame(kept, columns=["date", "move"]).set_index("date")
    out = pd.concat([df, add]).round(2)
    out = out[~out.index.duplicated(keep="last")].sort_index()
    out.to_csv(RAW / "move.csv")
    n_new = int((add.index > last).sum())
    return f"move: +{n_new} new, {len(add) - n_new} refreshed → {out.index[-1].date()}"


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
    # ⚠️ ETF 不用 settling 窗:auto_adjust=True 是「含息還原」,Yahoo 會因新除息「事後回頭重算」整段
    #    歷史 → 重抓舊 bar 會用當下(可能已漂移/壞)的還原值覆寫掉原本正確的捕捉(實測 2026-06-22
    #    0050 重抓後 +3.59%→+5.33% 錯掉)。指數(^TWII/^MOVE 無除息調整)才安全重抓。ETF 維持 append-only。
    new = y[(y.index > last) & (y.index <= _session_cutoff())]  # 擋 partial today bar(ETF 同台股交易)
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
