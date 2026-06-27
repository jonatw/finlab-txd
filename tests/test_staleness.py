"""掛鐘新鮮度 + generated_at 時區。
回歸測試 2026-06-22 事件:Yahoo 抓取失敗 → raw 卡 6/18,但 curve_stale 看不到(curve==raw),
線上訊號靜默過期。data_stale 用掛鐘對比 TWSE 應有收盤日才抓得到。"""
import datetime
from zoneinfo import ZoneInfo
import pandas as pd
from src.export import (_last_completed_session, _data_lag_sessions,
                        _last_us_session, _us_lag_sessions, main)

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


# === 絕對 MOVE 新鮮度(回歸 2026-06-25 事件:yfinance 靜默回傳過期 ^MOVE bar)===
# 舊 freshness 只比 MOVE vs TAIEX(相對)、且只進前端 warn,全來源一起 stale 時 CI 抓不到。
# 改用美股交易日曆【絕對】比對 + 進 CI hard-fail gate。

def test_us_lag_counts_xnys_sessions_with_juneteenth():
    # 6/19 Juneteenth(XNYS 休市)、6/20-21 週末。6/18(四)→ 最近美股交易日 6/22(一)= 落後 1。
    assert _us_lag_sessions(pd.Timestamp("2026-06-18"), pd.Timestamp("2026-06-22")) == 1
    # MOVE 凍在 6/22,但美股已到 6/24 → 漏 6/23+6/24 = 落後 2(= 靜默過期 bug 的形狀)。
    assert _us_lag_sessions(pd.Timestamp("2026-06-22"), pd.Timestamp("2026-06-24")) == 2
    assert _us_lag_sessions(pd.Timestamp("2026-06-24"), pd.Timestamp("2026-06-24")) == 0


def test_last_us_session_expects_prior_us_close_after_buffer():
    # 台灣 6/25 18:00(美東 6/25 06:00:6/24 收盤 ~14h 前、6/25 尚未開盤)→ expected = 6/24。
    now = datetime.datetime(2026, 6, 25, 18, 0, tzinfo=TW)
    assert _last_us_session(now).date() == datetime.date(2026, 6, 24)


def test_last_us_session_tolerates_just_closed_bar_in_early_run():
    # 台灣 6/25 05:30 盤前(美東 6/24 17:30:6/24 才剛收盤 ~1.5h < 2h buffer)→ 仍 expect 6/23,
    # = 早班容忍 MOVE 尚未 aggregate,不對「剛收盤還沒上 Yahoo」誤判 stale。
    now = datetime.datetime(2026, 6, 25, 5, 30, tzinfo=TW)
    assert _last_us_session(now).date() == datetime.date(2026, 6, 23)


def test_main_exposes_move_stale_field():
    # freshness 一定要有 move_stale / expected_us_session(CI gate 讀這個 hard-fail)。
    sig = main(now=datetime.datetime(2026, 6, 25, 18, 0, tzinfo=TW), write=False)
    fr = sig["freshness"]
    assert "move_stale" in fr and "expected_us_session" in fr and "move_us_lag_sessions" in fr
    assert isinstance(fr["move_stale"], bool)


def test_settling_window_overwrites_stale_preliminary_bar(tmp_path, monkeypatch):
    """回歸 2026-06-23 事件:盤中/preliminary ^TWII bar 被 append-only 永久凍結。
    settling 窗應在後續班次用 Yahoo 最終值覆寫最近 SETTLE_DAYS 內的舊 bar。"""
    from src import fetch
    monkeypatch.setattr(fetch, "RAW", tmp_path)
    # 已存:6/23 被存成「漲」的 preliminary 壞 bar(close 105,實際應為 99)
    stored = pd.DataFrame(
        {"open": [100, 100, 104], "high": [100, 100, 105], "low": [100, 100, 104],
         "close": [100.0, 100.0, 105.0]},
        index=pd.to_datetime(["2026-06-19", "2026-06-22", "2026-06-23"]),
    )
    stored.index.name = "date"; stored.to_csv(tmp_path / "taiex_twii.csv")
    # Yahoo 最終值:6/23 其實是跌(99)+ 新增 6/24(98)
    dates = pd.to_datetime(["2026-06-19", "2026-06-22", "2026-06-23", "2026-06-24"])
    closes = [100.0, 100.0, 99.0, 98.0]
    fresh = pd.DataFrame(
        {"Open": closes, "High": [c * 1.001 for c in closes],
         "Low": [c * 0.999 for c in closes], "Close": closes}, index=dates)
    monkeypatch.setattr(fetch, "_yf", lambda *a, **k: fresh)
    monkeypatch.setattr(fetch, "_session_cutoff", lambda *a, **k: pd.Timestamp("2026-06-24"))

    msg = fetch.update_taiex()
    out = pd.read_csv(tmp_path / "taiex_twii.csv", parse_dates=["date"]).set_index("date")
    assert out.loc["2026-06-23", "close"] == 99.0, "stale 6/23 應被最終值覆寫"
    assert out.loc["2026-06-24", "close"] == 98.0, "新交易日應 append"
    assert "refreshed" in msg


def _seed_xc(xc, tmp_path, monkeypatch):
    monkeypatch.setattr(xc, "RAW", tmp_path)
    monkeypatch.setattr(xc, "DERIVED", tmp_path)
    monkeypatch.setattr(xc, "XCHECK", tmp_path / "xcheck.json")
    monkeypatch.setattr(xc, "ETFS", ("0050",))


def test_crosscheck_autocorrects_taiex_and_etf(tmp_path, monkeypatch):
    """多源驗證:TAIEX 不符 → 覆寫;ETF 含息不符 → 用 TWSE(raw+股利)重建自動修正 level。"""
    from src import crosscheck as xc
    _seed_xc(xc, tmp_path, monkeypatch)
    dates = pd.to_datetime(["2026-06-22", "2026-06-23", "2026-06-24"])
    # stored 6/23 是「漲」的壞 bar;TWSE 權威是「跌」
    pd.DataFrame({"open": [100, 104, 101], "high": [100, 105, 101], "low": [100, 104, 101],
                  "close": [100.0, 105.0, 103.0]}, index=dates).rename_axis("date").to_csv(tmp_path / "taiex_twii.csv")
    pd.DataFrame({"adj": [100.0, 105.0, 103.0]}, index=dates).rename_axis("date").to_csv(tmp_path / "etf_0050.csv")
    tw_tx = pd.DataFrame({"open": [100, 103, 101], "high": [100, 103, 101], "low": [100, 99, 101],
                          "close": [100.0, 99.0, 97.0]}, index=dates)
    monkeypatch.setattr(xc, "twse_taiex", lambda last: tw_tx)
    monkeypatch.setattr(xc, "twse_close", lambda no, last: pd.Series([100.0, 99.0, 97.0], index=dates))
    monkeypatch.setattr(xc, "etf_distributions", lambda no: ({}, True))
    r = xc.run()
    fixed = pd.read_csv(tmp_path / "taiex_twii.csv", parse_dates=["date"]).set_index("date")
    assert fixed.loc["2026-06-23", "close"] == 99.0           # TAIEX 自動覆寫
    assert len(r["taiex_corrections"]) == 1
    etf = pd.read_csv(tmp_path / "etf_0050.csv", parse_dates=["date"]).set_index("date")["adj"]
    assert abs(etf.loc["2026-06-23"] - 99.0) < 1e-6           # ETF 含息重建:100×(1-1%)=99
    assert abs(etf.loc["2026-06-24"] - 97.0) < 1e-6           # 連帶 level 位移也校正
    assert any(c["etf"] == "0050" for c in r["etf_corrections"])
    assert not r["etf_flags"] and r["mismatch"] is False


def test_crosscheck_suppresses_exdiv_on_etf(tmp_path, monkeypatch):
    """ETF 除息日:重建含息報酬=raw+股利 與 stored 相符 → 不修正、不誤報(記 etf_exdiv)。"""
    from src import crosscheck as xc
    _seed_xc(xc, tmp_path, monkeypatch)
    dates = pd.to_datetime(["2026-06-22", "2026-06-23"])
    monkeypatch.setattr(xc, "twse_taiex", lambda last: pd.DataFrame(
        {"open": [100, 100], "high": [100, 100], "low": [100, 100], "close": [100.0, 100.0]}, index=dates))
    # stored含息 6/23 = -1%(含回息);TWSE raw = -3%;股利=2(prev 100 → 2%)→ 重建 = -1% = 相符
    pd.DataFrame({"open": [100, 100], "high": [100, 100], "low": [100, 100], "close": [100.0, 100.0]},
                 index=dates).rename_axis("date").to_csv(tmp_path / "taiex_twii.csv")
    pd.DataFrame({"adj": [100.0, 99.0]}, index=dates).rename_axis("date").to_csv(tmp_path / "etf_0050.csv")
    monkeypatch.setattr(xc, "twse_close", lambda no, last: pd.Series([100.0, 97.0], index=dates))
    monkeypatch.setattr(xc, "etf_distributions", lambda no: ({pd.Timestamp("2026-06-23"): 2.0}, True))
    r = xc.run()
    assert not r["etf_flags"] and not r["etf_corrections"]     # 相符 → 不動
    assert any(e["etf"] == "0050" for e in r["etf_exdiv"])     # 認出是除息
    assert r["mismatch"] is False


def test_crosscheck_flags_etf_when_dividend_fetch_fails(tmp_path, monkeypatch):
    """股利抓取失敗(divs_ok=False)→ 不自動改 ETF(避免誤剝股利),改 flag 交人工。"""
    from src import crosscheck as xc
    _seed_xc(xc, tmp_path, monkeypatch)
    dates = pd.to_datetime(["2026-06-22", "2026-06-23"])
    monkeypatch.setattr(xc, "twse_taiex", lambda last: pd.DataFrame(
        {"open": [100, 100], "high": [100, 100], "low": [100, 100], "close": [100.0, 100.0]}, index=dates))
    pd.DataFrame({"open": [100, 100], "high": [100, 100], "low": [100, 100], "close": [100.0, 100.0]},
                 index=dates).rename_axis("date").to_csv(tmp_path / "taiex_twii.csv")
    pd.DataFrame({"adj": [100.0, 105.0]}, index=dates).rename_axis("date").to_csv(tmp_path / "etf_0050.csv")
    monkeypatch.setattr(xc, "twse_close", lambda no, last: pd.Series([100.0, 99.0], index=dates))
    monkeypatch.setattr(xc, "etf_distributions", lambda no: ({}, False))   # 抓取失敗
    r = xc.run()
    before = pd.read_csv(tmp_path / "etf_0050.csv", parse_dates=["date"]).set_index("date")["adj"]
    assert before.loc["2026-06-23"] == 105.0                   # 未自動改
    assert any(f["etf"] == "0050" for f in r["etf_flags"]) and r["mismatch"] is True
