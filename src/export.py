"""curve.csv + raw → site/data/{signal,nav}.json(餵 index.html)。finlab-free port。

結構與 monorepo export_txd_dashboard.py 一致,讓既有 index.html 不改即可用。
唯讀資料,只寫 JSON。
"""
from __future__ import annotations
import json
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
from pathlib import Path
import numpy as np
import pandas as pd
from src.strategy import ATR_WIN, DTP_LOOKBACK, DTP_THRESH
from src.config import PAPER_DEPLOY_DATE, PAPER_STAGE, PAPER_LANE_HEALTH
import exchange_calendars as xcals

_WEEKDAY_TW = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]
TW = ZoneInfo("Asia/Taipei")
TWSE_CLOSE = dtime(13, 30)  # 台股現貨收盤


def _next_trading_session(ref):
    """ref 之後第一個 TWSE 真實交易日(認台股假期,如端午/中秋/農曆年);失敗 fallback BDay(1)。
    回 (Timestamp, 週幾, 是否精確)。避免把假期當下單日(降信度)。"""
    try:
        s = xcals.get_calendar("XTAI").sessions_in_range(
            ref + pd.Timedelta(days=1), ref + pd.Timedelta(days=30))
        if len(s):
            d = pd.Timestamp(s[0])
            return d, _WEEKDAY_TW[d.weekday()], True
    except Exception:
        pass
    d = ref + pd.offsets.BDay(1)
    return d, _WEEKDAY_TW[d.weekday()], False


def _last_completed_session(now_tw):
    """以 13:30 TWT 收盤為界,當下『收盤已過』的最近 TWSE 交易日(認假期)。
    fetch 失敗時 raw 不前進,靠這個對掛鐘比對才抓得到『訊號過期』(curve_stale 看不到)。"""
    try:
        cal = xcals.get_calendar("XTAI")
        today = pd.Timestamp(now_tw.date())
        sess = cal.sessions_in_range(today - pd.Timedelta(days=20), today)
        if len(sess) == 0:
            return None
        last = pd.Timestamp(sess[-1])
        if last.date() == now_tw.date() and now_tw.time() < TWSE_CLOSE:
            sess = sess[:-1]  # 今天還沒收盤 → 退到前一個交易日
            last = pd.Timestamp(sess[-1]) if len(sess) else None
        return last
    except Exception:
        return None


def _last_us_session(now_tw, min_hours_since_close=2.0):
    """當下『MOVE 應已可取得』的最近 XNYS(美股)交易日 — 用來【絕對】比對 move.csv 是否靜默過期。
    背景:Yahoo bulk daily endpoint 曾靜默回傳過期 ^MOVE bar(fetch 不 raise、只『0 new』),
    舊 freshness 只比 MOVE vs TAIEX(相對),全來源一起 stale 時看起來『正常』→ CI 抓不到。
    這裡改用美股交易日曆【絕對】比對(認美股假期如 Juneteenth)。MOVE 美股收盤後 ~30min 上 Yahoo,
    min_hours buffer 避免早班(剛收盤、aggregate 慢)誤判。失敗回 None(不誤殺)。"""
    try:
        cal = xcals.get_calendar("XNYS")
        now_utc = pd.Timestamp(now_tw.astimezone(ZoneInfo("UTC")))
        sess = cal.sessions_in_range(pd.Timestamp(now_utc.date()) - pd.Timedelta(days=20),
                                     pd.Timestamp(now_utc.date()))
        for s in reversed(list(sess)):
            close = cal.session_close(pd.Timestamp(s))  # tz-aware UTC
            if (now_utc - close).total_seconds() >= min_hours_since_close * 3600:
                return pd.Timestamp(s).tz_localize(None).normalize()
        return None
    except Exception:
        return None


def _us_lag_sessions(move_last, expected_us):
    """move.csv 最後日落後『應有的最近美股收盤日』幾個 XNYS 交易日;0 = 不落後。"""
    if expected_us is None or expected_us <= move_last:
        return 0
    try:
        cal = xcals.get_calendar("XNYS")
        return int(len(cal.sessions_in_range(move_last + pd.Timedelta(days=1), expected_us)))
    except Exception:
        return int(max(np.busday_count(move_last.date(), expected_us.date()), 0))


def _signal_ref(cv_index, now_tw):
    """訊號基準日 = curve 中 ≤『當下已收盤(過 13:30)交易日』的最後一列(時間感知)。
    擋掉 partial today bar / 提前列把 for_session 誤推到隔天。盤前→昨天、收盤後→今天。
    日曆失敗(last_done=None)→ 退回 curve 最後一列(維持原行為,不更糟)。"""
    ref = cv_index[-1]
    last_done = _last_completed_session(now_tw)
    if last_done is not None and ref > last_done:
        earlier = cv_index[cv_index <= last_done]
        if len(earlier):
            ref = earlier[-1]
    return ref


def _data_lag_sessions(ref, expected):
    """ref(最後資料日)落後 expected(應有的最近收盤日)幾個 TWSE 交易日;0 = 不落後。"""
    if expected is None or expected <= ref:
        return 0
    try:
        cal = xcals.get_calendar("XTAI")
        return int(len(cal.sessions_in_range(ref + pd.Timedelta(days=1), expected)))
    except Exception:
        return int(max(np.busday_count(ref.date(), expected.date()), 0))


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "site" / "data"
CURVE = ROOT / "data" / "derived" / "curve.csv"
POS_TXT = {0: "空手 / 平倉", 1: "台指期 1x 做多", 2: "台指期 2x 做多"}


def _series(name, col="adj"):
    df = pd.read_csv(RAW / name, parse_dates=["date"]).set_index("date")
    return df[col].astype(float)


def main(now=None, write=True):
    """now: 可注入的 tz-aware 當下時間(預設 datetime.now(TW));測試用以固定掛鐘。
    write=False: 只計算回傳 signal dict,不落地檔案(測試用,不污染 working tree)。"""
    now_tw = now if now is not None else datetime.now(TW)
    if now_tw.tzinfo is None:
        now_tw = now_tw.replace(tzinfo=TW)
    OUT.mkdir(parents=True, exist_ok=True)
    cv = pd.read_csv(CURVE, parse_dates=["date"]).set_index("date")
    # 時間感知訊號基準日(擋 partial today bar / 提前列把 for_session 誤推到隔天 → 不論幾點都正確)
    ref = _signal_ref(cv.index, now_tw)
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
    # 掛鐘新鮮度:抓取失敗時 raw 不前進,curve_stale 看不到 → 用『應有的最近收盤日』對比
    expected_session = _last_completed_session(now_tw)
    data_lag = _data_lag_sessions(ref, expected_session)
    data_stale = data_lag > 0
    # 【絕對】MOVE 新鮮度:用美股交易日曆比對 raw move.csv 最後日 → 抓 Yahoo 靜默回傳過期 bar。
    # 舊的 move_lag 是相對(MOVE vs TAIEX),全來源一起 stale 會被騙過、且只進前端 warn;
    # 這個比真實 XNYS 收盤日,並進 CI hard-fail gate(末班/手動),才擋得住靜默過期。
    move_raw_last = pd.Timestamp(move_df.index[-1])
    expected_us_session = _last_us_session(now_tw)
    move_us_lag = _us_lag_sessions(move_raw_last, expected_us_session)
    move_stale = move_us_lag > 0
    for_session, for_session_wd, fs_exact = _next_trading_session(ref)
    exp_sig = cv["exposure"]
    exp_held = exp_sig.shift(1).fillna(0.0)
    _rpos = cv.index.get_loc(ref)  # 用 ref(已收盤基準日)取訊號,非盲取最後一列
    target = 0.0 if gated_next else float(exp_sig.iloc[_rpos])
    prev = float(exp_sig.iloc[_rpos - 1]) if _rpos >= 1 else 0.0
    changed = abs(target - prev) > 1e-9
    action = "不需調倉" if not changed else ("加碼" if target > prev else "減碼")

    signal = {
        "px_as_of": str(ref.date()), "move_as_of": str(move_as_of.date()),
        "for_session": str(for_session.date()), "for_session_weekday": for_session_wd, "for_session_approx": not fs_exact,
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
        "status": {"stage": PAPER_STAGE, "lane_health": PAPER_LANE_HEALTH, "deploy_date": PAPER_DEPLOY_DATE,
                   "note": f"TXD paper-lane 起算 {PAPER_DEPLOY_DATE}(紙上追蹤,非實單對帳)。已過 look-ahead + overfit 兩道稽核;live 期望 Sharpe ~1.35"},
        "freshness": {"px_index": str(ref.date()), "move": str(move_as_of.date()),
                      "curve_stale": curve_stale, "market_latest": str(market_latest.date()),
                      "move_lag_bdays": move_lag,
                      "expected_last_session": str(expected_session.date()) if expected_session is not None else None,
                      "data_lag_sessions": data_lag, "data_stale": data_stale,
                      "expected_us_session": str(expected_us_session.date()) if expected_us_session is not None else None,
                      "move_us_lag_sessions": move_us_lag, "move_stale": move_stale,
                      "stale_warn": bool(move_lag > 1 or curve_stale or data_stale or move_stale),
                      "note": "MOVE 是美債波動, 正常晚台股 1 個交易日; curve_stale=true 表示策略 curve 還沒重生到最新交易日; "
                              "data_stale=true 表示 TAIEX 落後台股(XTAI)交易日; move_stale=true 表示 ^MOVE 落後美股(XNYS)交易日"
                              "(Yahoo 靜默回傳過期 bar)→ data_stale/move_stale 皆進 CI hard-fail gate, 訊號過期先別照做"},
        "generated_at": now_tw.isoformat(timespec="seconds"),
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
    if write:
        # 冪等:若除了 generated_at 之外無實質變化,保留舊時戳 → 不產生 diff → 重試窗多班不刷 commit
        sig_path = OUT / "signal.json"
        if sig_path.exists():
            try:
                old = json.loads(sig_path.read_text())
                if {k: v for k, v in old.items() if k != "generated_at"} == \
                   {k: v for k, v in signal.items() if k != "generated_at"}:
                    signal["generated_at"] = old.get("generated_at", signal["generated_at"])
            except Exception:  # noqa: BLE001
                pass
        sig_path.write_text(json.dumps(signal, ensure_ascii=False, indent=2))
        (OUT / "nav.json").write_text(json.dumps(nav, ensure_ascii=False, separators=(",", ":")))
        print(f"✓ signal.json: {ref.date()} target {target}x DTP {dtp_ref*100:.0f}%{' 🚨' if gated_next else ''}")
        print(f"✓ nav.json: {len(cv)} 天, updated {nav['updated']}, 關機日 {sum(nav['series']['dtp_gated'])}")
    return signal


if __name__ == "__main__":
    main()
