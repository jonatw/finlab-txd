"""seed↔Yahoo 接縫:raw 在 seed cutoff 邊界連續(無跳空/對不齊)。
post-cutoff 尚無 Yahoo bar 時 → 驗 raw 到 cutoff 存在且單調;有了之後 → 驗接縫日 return 合理。"""
import json
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def test_seam_continuity(taiex):
    cutoff = pd.Timestamp(json.loads((ROOT / "data/seed/MANIFEST.json").read_text())["cutoff"])
    assert (taiex.index <= cutoff).any(), "raw 應含 seed cutoff 之前的資料"
    assert taiex.index.is_monotonic_increasing and taiex.index.is_unique, "raw 日期須單調且唯一(接縫去重)"
    post = taiex[taiex.index > cutoff]
    if len(post):  # Yahoo 已 append post-cutoff bar → 驗接縫無跳空
        seam_ret = post["close"].iloc[0] / taiex.loc[:cutoff, "close"].iloc[-1] - 1
        assert abs(seam_ret) < 0.11, f"seam jump {seam_ret:.3f} at {post.index[0].date()} (壞 tick / 對不齊?)"
