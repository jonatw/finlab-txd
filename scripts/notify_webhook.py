"""push 通知:訊號『有變』(signal.changed==true)才 POST webhook。其餘情況乾淨退出。

由 daily.yml 在 commit & push 後呼叫,gated on repo 變數 NOTIFY_WEBHOOK_URL。
- 無變化 → 不送。
- WEBHOOK 未設 → 跳過(daily.yml 已用 if: 守,這裡再防一層)。
- 送失敗 → 非致命(不讓 flaky 接收端弄垮每日管線)。
- 設了 WEBHOOK_SECRET → 加 HMAC-SHA256 簽章(X-TXD-Signature),接收端可驗真。
單檔、可本地測:WEBHOOK=https://… python scripts/notify_webhook.py
"""
import hashlib
import hmac
import json
import os
import sys
import urllib.request
from pathlib import Path

SIG = Path(__file__).resolve().parents[1] / "site" / "data" / "signal.json"


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    stale_mode = "--stale" in argv  # 訊號過期告警(資料落後實際交易日,通常 Yahoo 抓取失敗)
    s = json.loads(SIG.read_text())
    fr = s.get("freshness", {})
    if stale_mode:
        if not fr.get("data_stale"):
            print("data fresh; no stale alert.")
            return 0
        event, extra = "signal.stale", {
            "px_as_of": s.get("px_as_of"),
            "expected_last_session": fr.get("expected_last_session"),
            "data_lag_sessions": fr.get("data_lag_sessions"),
            "warn": "訊號過期(抓取落後實際交易日)— 別照此訊號下單",
        }
    else:
        if not s.get("changed"):
            print("signal unchanged; no webhook.")
            return 0
        event, extra = "signal.changed", {
            "for_session": s["for_session"],
            "target_exposure": s["target_exposure"],
            "prev_exposure": s.get("prev_exposure"),
            "action": s["action"],
            "pos_text": s.get("pos_text"),
            "gated_next": s["dtp"]["gated_next"],
        }
    url = os.environ.get("WEBHOOK")
    if not url:
        print(f"{event} but WEBHOOK unset; skip.")
        return 0
    payload = json.dumps({
        "event": event, **extra,
        "url": "https://txd.av8r.tw/data/signal.json",
        "note": "research only, not investment advice",
    }, ensure_ascii=False).encode("utf-8")
    headers = {"content-type": "application/json"}
    secret = os.environ.get("WEBHOOK_SECRET")
    if secret:
        headers["X-TXD-Signature"] = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    try:
        urllib.request.urlopen(urllib.request.Request(url, data=payload, headers=headers), timeout=15).read()
        print(f"webhook sent: {event} ({s['for_session']})")
    except Exception as e:  # noqa: BLE001 — 非致命,不讓接收端弄垮管線
        print("webhook failed (non-fatal):", str(e)[:100])
    return 0


if __name__ == "__main__":
    sys.exit(main())
