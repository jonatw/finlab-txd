"""訊號顯示日期『時間感知』:盤前/盤後都顯示正確 for_session;擋 partial today bar 把訊號推到隔天。

回歸 2026-06-23 事件:早上盤前(期貨未開)fetch 漏進今天 partial bar → ref=今天 → for_session=隔天。
修法:① export._signal_ref 用『當下已收盤交易日』當基準(盤前退回昨天);② fetch._session_cutoff 不 append 未收盤的 today bar。
"""
import datetime
from zoneinfo import ZoneInfo
import pandas as pd
from src.export import _signal_ref, _next_trading_session, main
from src.fetch import _session_cutoff

TW = ZoneInfo("Asia/Taipei")


def _idx(*dates):
    return pd.DatetimeIndex([pd.Timestamp(d) for d in dates])


def test_signal_ref_caps_partial_today_bar_premarket():
    # curve 漏進今天(6/23)partial bar;盤前 08:30(未過 13:30)→ ref 退回 6/22 → for_session=今天非隔天
    cv_idx = _idx("2026-06-18", "2026-06-22", "2026-06-23")
    now = datetime.datetime(2026, 6, 23, 8, 30, tzinfo=TW)
    ref = _signal_ref(cv_idx, now)
    assert ref.date() == datetime.date(2026, 6, 22)
    fs, _, _ = _next_trading_session(ref)
    assert fs.date() == datetime.date(2026, 6, 23)  # 今天,不是 6/24


def test_signal_ref_keeps_today_after_close():
    # 收盤後 14:30,資料正常含今天 → ref=6/23 → for_session=隔天
    cv_idx = _idx("2026-06-22", "2026-06-23")
    now = datetime.datetime(2026, 6, 23, 14, 30, tzinfo=TW)
    assert _signal_ref(cv_idx, now).date() == datetime.date(2026, 6, 23)


def test_signal_ref_noop_when_clean():
    # 正常:curve 最後 = 已收盤交易日 → 不動
    cv_idx = _idx("2026-06-18", "2026-06-22")
    now = datetime.datetime(2026, 6, 23, 8, 30, tzinfo=TW)
    assert _signal_ref(cv_idx, now).date() == datetime.date(2026, 6, 22)


def test_fetch_cutoff_premarket_vs_postclose():
    pre = datetime.datetime(2026, 6, 23, 8, 30, tzinfo=TW)
    post = datetime.datetime(2026, 6, 23, 14, 30, tzinfo=TW)
    assert _session_cutoff(pre) == pd.Timestamp("2026-06-22")   # 盤前 → 擋今天 partial
    assert _session_cutoff(post) == pd.Timestamp("2026-06-23")  # 收盤後 → 含今天


def test_main_for_session_premarket_is_today_not_tomorrow():
    # 真實乾淨資料 + 盤前 08:30 → for_session 應是 px_as_of 的下一交易日(今天),非再隔一天
    sig = main(now=datetime.datetime(2026, 6, 23, 8, 30, tzinfo=TW), write=False)
    assert pd.Timestamp(sig["for_session"]) > pd.Timestamp(sig["px_as_of"])
    # for_session 不該超過『px_as_of 的下一個交易日』
    nxt, _, _ = _next_trading_session(pd.Timestamp(sig["px_as_of"]))
    assert pd.Timestamp(sig["for_session"]) == nxt
