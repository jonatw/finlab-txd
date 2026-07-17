"""blend_pcr 追蹤線(nav.json series)正確性:對齊、起算前 None、值 = 50/50 日報酬複利。
追蹤線純顯示(user 裁決 2026-07-18:部署仍 TXD 單獨),但顯示值也不能錯。"""
import json
from pathlib import Path
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def nav():
    return json.loads((ROOT / "site" / "data" / "nav.json").read_text())


def test_blend_aligned_and_prefix_none(nav):
    s = nav["series"]
    assert "blend_pcr" in s, "nav.json 缺 blend_pcr(export 後才有;先跑 pipeline --no-fetch)"
    assert len(s["blend_pcr"]) == len(s["date"])
    # PCR 資料 2010 起 → 1999 段必為 None(不畫);尾端必有值
    assert s["blend_pcr"][0] is None
    assert s["blend_pcr"][-1] is not None


def test_blend_value_matches_recompute(nav):
    """尾端 blend NAV 相對值 = 用兩腿 pnl 獨立重算(容差 1e-3,round 誤差)。"""
    cv = pd.read_csv(ROOT / "data" / "derived" / "curve.csv", parse_dates=["date"]).set_index("date")
    pc_df = pd.read_csv(ROOT / "data" / "derived" / "pcr_curve.csv", parse_dates=["date"]).set_index("date")
    # 同 export 遮罩:P/C ratio 資料存在才起算(pcr_curve 全時段有列,資料前 pnl=0 是 flat 不是 blend)
    has_pc = pc_df["pcr"].notna().reindex(cv.index, fill_value=False)
    pnl = (0.5 * cv["pnl"] + 0.5 * pc_df["pnl"].reindex(cv.index)).where(has_pc)
    nav_b = (1.0 + pnl.dropna()).cumprod()
    s = nav["series"]
    vals = [v for v in s["blend_pcr"] if v is not None]
    assert len(vals) == len(nav_b)
    assert abs(vals[-1] / vals[0] - nav_b.iloc[-1] / nav_b.iloc[0]) < 1e-3


def test_blend_never_blocks_main_series(nav):
    """blend 缺料時全 None 也不能影響主曲線欄位(結構保證:nav/benchmark 完整)。"""
    s = nav["series"]
    assert all(v is not None for v in s["nav"])
    assert all(v is not None for v in s["benchmark"])
