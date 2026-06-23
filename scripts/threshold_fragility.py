"""TXD 三道門檻『邊緣脆弱度』季度稽核(只讀、不動策略 → 不觸發 audit-on-change)。

問:策略在三個門檻(① MOVE 槓桿線、② DTP 關艙線 0.96、③ 均線 spine)的邊緣有多少天?
    那些 near-miss 之後市場怎麼走?多層設計(spine/lev/DTP)有沒有互相補位?

用途:每季跑一次,看『脆弱度輪廓』有沒有漂移(near-miss 是否開始群聚、spine 是否還能補 DTP 的洞)。
**這是 monitoring 工具,不是調參依據** —— 拿單一事件去調門檻 = 過擬(見本檔結論)。

跑:.venv/bin/python -m scripts.threshold_fragility
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
ATR_WIN, DTP_LOOKBACK, DTP_THRESH = 14, 250, 0.96


def _signals():
    tx = pd.read_csv(RAW / "taiex_twii.csv", parse_dates=["date"]).set_index("date")
    mv = pd.read_csv(RAW / "move.csv", parse_dates=["date"]).set_index("date")["move"]
    idx = tx["close"].astype(float); hi = tx["high"].astype(float); lo = tx["low"].astype(float)
    cal = idx.index; ret = idx.pct_change()
    move = mv.reindex(cal, method="ffill"); med = move.rolling(252, min_periods=120).quantile(0.5)
    move_low = move < med
    ma = {w: idx.rolling(w).mean() for w in (60, 120, 200)}
    spine = pd.concat([(idx > ma[w]).astype(float) for w in (60, 120, 200)], axis=1).mean(axis=1)
    tr = pd.concat([hi - lo, (hi - idx.shift(1)).abs(), (lo - idx.shift(1)).abs()], axis=1).max(axis=1)
    atr_pct = tr.ewm(alpha=1 / ATR_WIN, adjust=False).mean() / idx * 100
    dtp = atr_pct.rolling(DTP_LOOKBACK).apply(lambda x: (x[-1] >= x).mean(), raw=True)
    lev = pd.Series(np.where(move_low, 2.0, 1.0), index=cal)
    exposure = (spine * lev * (dtp < DTP_THRESH)).clip(0, 2)
    return dict(idx=idx, ret=ret, move=move, med=med, move_low=move_low, ma=ma,
               spine=spine, dtp=dtp, lev=lev, exposure=exposure, cal=cal)


def _fwd(idx, n):
    return (idx.shift(-n) / idx - 1) * 100


def _fwd_min(idx, n=20):
    v = idx.values; out = np.full(len(v), np.nan)
    for i in range(len(v) - n):
        out[i] = v[i + 1:i + 1 + n].min() / v[i] - 1
    return pd.Series(out * 100, index=idx.index)


def main():
    s = _signals(); idx = s["idx"]; cal = s["cal"]
    valid = s["dtp"].notna() & s["med"].notna()
    f5, f10, f20 = _fwd(idx, 5), _fwd(idx, 10), _fwd(idx, 20); fmin = _fwd_min(idx, 20)
    print(f"=== TXD 門檻脆弱度稽核 | {cal[0].date()}~{cal[-1].date()} | 有效 {int(valid.sum())} 天 ===")

    def fwd_row(mask, name):
        m = mask & f20.notna() & valid
        print(f"  {name:20} n={int(m.sum()):>4} | 後5 {f5[m].mean():+5.2f}% 後10 {f10[m].mean():+5.2f}% 後20 {f20[m].mean():+5.2f}% "
              f"| 後20最壞中位 {fmin[m].median():+5.1f}% <-10%占{(fmin[m] < -10).mean() * 100:.0f}%")

    # ① 槓桿線
    ratio = (s["move"] / s["med"] - 1)
    flip = (s["move_low"] != s["move_low"].shift(1)) & valid
    near_lev = (ratio.abs() < 0.02) & valid
    print("\n[①槓桿 2x↔1x] 翻轉 %d 次(~%.0f/年) | 卡線±2%% %d 天" %
          (int(flip.sum()), flip.sum() / (valid.sum() / 252), int(near_lev.sum())))
    fwd_row(valid, "全部(基準)"); fwd_row(near_lev, "卡槓桿線±2%")

    # ② 關艙線
    shut = (s["dtp"] >= DTP_THRESH) & valid
    graze = (s["dtp"] >= 0.94) & (s["dtp"] < DTP_THRESH) & valid
    print("\n[②關艙 DTP≥%.2f] 關艙 %d 天 | 擦邊0.94-0.96 %d 天" % (DTP_THRESH, int(shut.sum()), int(graze.sum())))
    fwd_row(graze, "擦邊沒關"); fwd_row(shut, "實際關艙")
    # 多層補位:擦邊沒關當下 spine 已經砍到多低?(spine 低 = 別層已補位 = 灰區其實安全)
    g = graze & valid
    covered = (s["spine"][g] <= 0.34).mean() * 100
    print(f"  ⮑ 多層補位:擦邊沒關當下 spine≤0.34(均線已砍光)占 {covered:.0f}% → 這比例越高,DTP 灰區越被 spine 蓋掉")

    # ③ 均線 spine
    sp_flip = (s["spine"] != s["spine"].shift(1)) & valid
    near_ma = pd.Series(False, index=cal)
    for w in (60, 120, 200):
        near_ma |= (idx / s["ma"][w] - 1).abs() < 0.01
    near_ma &= valid
    fl = (s["spine"] != s["spine"].shift(1)).values
    ii = cal.get_indexer(cal[near_ma]); whip = sum(1 for i in ii if i + 10 < len(cal) and fl[i + 1:i + 11].sum() >= 2)
    print("\n[③均線 spine] 穿越 %d 次(~%.0f/年) | 貼線±1%% %d 天 | 後10日雙巴 %.0f%%" %
          (int(sp_flip.sum()), sp_flip.sum() / (valid.sum() / 252), int(near_ma.sum()), whip / max(near_ma.sum(), 1) * 100))
    fwd_row(near_ma, "貼均線±1%")

    print("\n=== 季度判讀提示 ===")
    print("  · 槓桿線 near-miss 後續≈基準 → robust。關艙擦邊後續偏弱(<-10%占比看上面)= 真灰區,")
    print("    但看『多層補位』%:若高,spine 已蓋掉 → 不必動 DTP。均線雙巴%高但 3 均線稀釋成本。")
    print("  · 觀察『漂移』:若擦邊<-10%占比、雙巴%、補位% 跨季大變 → 才是真信號;單季快照別調參(過擬)。")


if __name__ == "__main__":
    main()
