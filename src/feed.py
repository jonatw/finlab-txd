"""signal.json → site/feed.json(JSON Feed 1.1)。每交易日一則,鍵 for_session,保留最後 60 則。冪等。

agent/reader 可訂閱輪詢(ETag 條件式 GET 省頻寬);_txd 擴充物件帶機器欄位,免解析 content_text。
date_published 用 for_session 的台股收盤時刻(穩定、tz 正確;不靠 runner 時間)。
"""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIG = ROOT / "site" / "data" / "signal.json"
OUT = ROOT / "site" / "feed.json"
MAXITEMS = 60


def main():
    s = json.loads(SIG.read_text())
    fs = s["for_session"]
    item = {
        "id": fs,
        "url": f"https://txd.av8r.tw/#{fs}",
        "title": f"{fs} — {s['pos_text']}({s['action']})",
        "content_text": (
            f"target_exposure={s['target_exposure']} (prev {s['prev_exposure']}, changed={str(s['changed']).lower()}). "
            f"spine={s['spine']['value']} (站上 {s['spine']['n_above']}/3 均線). "
            f"MOVE={s['move']['value']} vs median252 {s['move']['median252']} → {s['move']['mult']}x. "
            f"DTP pct {s['dtp']['percentile']} ({'高波動關機' if s['dtp']['gated_next'] else '未關機'}). "
            f"研究用,非投資建議。"
        ),
        "date_published": f"{fs}T13:30:00+08:00",
        "_txd": {
            "target_exposure": s["target_exposure"],
            "changed": s["changed"],
            "gated_next": s["dtp"]["gated_next"],
        },
    }
    feed = json.loads(OUT.read_text()) if OUT.exists() else {}
    items = [i for i in feed.get("items", []) if i.get("id") != fs]
    items.insert(0, item)
    items = items[:MAXITEMS]
    out = {
        "version": "https://jsonfeed.org/version/1.1",
        "title": "TXD 台指期擇時訊號",
        "home_page_url": "https://txd.av8r.tw/",
        "feed_url": "https://txd.av8r.tw/feed.json",
        "description": "Daily target-exposure signal for the TXD timing strategy. Research only, not advice.",
        "items": items,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"✓ feed.json: {len(items)} 則, latest {fs}")


if __name__ == "__main__":
    main()
