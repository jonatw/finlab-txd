"""掛鐘新鮮度 + generated_at 時區。
回歸測試 2026-06-22 事件:Yahoo 抓取失敗 → raw 卡 6/18,但 curve_stale 看不到(curve==raw),
線上訊號靜默過期。data_stale 用掛鐘對比 TWSE 應有收盤日才抓得到。"""
import datetime
from zoneinfo import ZoneInfo
import pandas as pd
from src.export import _last_completed_session, _data_lag_sessions, main

TW = ZoneInfo("Asia/Taipei")


def test_data_lag_counts_trading_sessions_not_calendar_days():
    # 6/18(四)交易,6/19 端午,6/20-21 週末,6/22(一)交易
    assert _data_lag_sessions(pd.Timestamp("2026-06-18"), pd.Timestamp("2026-06-18")) == 0
    assert _data_lag_sessions(pd.Timestamp("2026-06-18"), pd.Timestamp("2026-06-22")) == 1


def test_last_completed_session_respects_1330_close():
    after = datetime.datetime(2026, 6, 22, 18, 0, tzinfo=TW)   # 收盤後
    before = datetime.datetime(2026, 6, 22, 10, 0, tzinfo=TW)  # 收盤前
    assert _last_completed_session(after).date() == datetime.date(2026, 6, 22)
    # 今天還沒收盤 → 退到前一交易日(6/19-21 不交易 → 6/18)
    assert _last_completed_session(before).date() == datetime.date(2026, 6, 18)


def test_main_flags_data_stale_when_behind_wallclock():
    """curve 落在 6/18,掛鐘已 6/22 晚上 → data_stale=True 且 stale_warn=True。"""
    sig = main(now=datetime.datetime(2026, 6, 22, 18, 0, tzinfo=TW), write=False)
    fr = sig["freshness"]
    # 只有當磁碟上的 curve 確實 <= 6/22 才成立(平時資料就是 frozen seed,故穩定)
    if pd.Timestamp(fr["px_index"]) < pd.Timestamp("2026-06-22"):
        assert fr["data_stale"] is True
        assert fr["stale_warn"] is True
        assert fr["data_lag_sessions"] >= 1


def test_generated_at_is_timezone_aware():
    sig = main(now=datetime.datetime(2026, 6, 22, 18, 0, tzinfo=TW), write=False)
    assert sig["generated_at"].endswith("+08:00")          # 不再是 naive
    assert datetime.datetime.fromisoformat(sig["generated_at"]).tzinfo is not None
