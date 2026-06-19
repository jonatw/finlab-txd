# finlab-txd — TXD 擇時策略儀表板(serverless, finlab-free)

TXD = **TX 分級順勢 × MOVE 槓桿 + DTP% 高波動關機濾網** 的台指期擇時策略,每日自動更新的公開儀表板。
從 finlab 研究 monorepo spin-out 成**獨立、零付費依賴、可完整稽核**的專案。

**Live:** https://txd.av8r.tw

---

## 策略一句話
- **spine**:加權指數(^TWII)站上 MA60/120/200 的比例(0 / .33 / .67 / 1)。
- **lev**:MOVE(美債波動)< 自身 252 日中位 → 2x 加碼,否則 1x。
- **DTP 關機**:Wilder-ATR(14)% 的 250 日百分位,昨日衝進 top-4%(發瘋日)→ 今日空手。
- 進場 T+1、成本 2bps/單邊。時序安全 by construction(`exposure.shift(1)`、DTP 用 t-1)。
- 已過 look-ahead + overfit 兩道稽核;**參數凍結**。誠實 live 期望 Sharpe ~1.35。

## 架構(serverless)
```
GitHub Actions (cron 每日)  ──fetch Yahoo──▶  data/raw/*.csv  (git = 資料庫 + 稽核日誌)
        │ rebuild → metrics → export
        ▼
   site/ (index.html + data/*.json)  ──push──▶  Cloudflare Pages 自動部署 (txd.av8r.tw)
```
- **零外部資料庫**:git repo 本身就是儲存層,每日一個 diff-able commit = 不可竄改稽核日誌。
- **零付費憑證**:不需要 finlab token;公開站走 CF Pages Git 整合,連部署 token 都免。

## 資料來源與準確度(全部實測對齊 finlab)
| 序列 | 來源 | 實測 vs finlab |
|---|---|---|
| TAIEX OHLC(訊號/ATR/benchmark) | Yahoo `^TWII` | close 全段 mean\|diff\| **0.0002%**;high/low 近期完全相同 |
| MOVE(槓桿開關) | Yahoo `^MOVE` | 24 年 **bit-exact**(max 0.0069%) |
| 0050/0056/00631L 對照(含息) | Yahoo `*.TW` | 日 return corr **0.9999+**;固定比例縮放,前端正規化後線形相同 |

## 資料分層(`data/`)
- **raw/**(神聖,append-only,CSV 可 git diff):`taiex_twii.csv`(O/H/L/C)、`move.csv`、`etf_{0050,0056,00631L}.csv`。
- **seed/MANIFEST.json**:seed cutoff(2026-06-18)+ 各檔 sha256。**cutoff 之前 = finlab(canonical, 凍結),永不被 Yahoo 覆寫**;之後由 Yahoo 增量。
- **derived/**(可重生,永不手改):`curve.csv`(strategy/benchmark/exposure/pnl/nav/dtp_gated)、`metrics_daily.csv`(各窗 Sharpe/CAGR/MDD 時序)。
- **golden/expected.json**:凍結錨點(nav@日期、全期 Sharpe/MDD、關機天數)→ 防數字悄悄漂移。

### 為什麼一定要 seed(關鍵)
實測:**純 Yahoo 重建全段歷史會偏 −13.5% NAV**(73 個曝險翻轉日,全在 2020 前 —— 早期零星壞 tick 在 MA 交叉點翻轉 spine、永久分叉)。
但 **2020+ 零分歧**,近期 Yahoo 收盤與 finlab 完全相同 → `finlab seed(凍結)+ Yahoo 增量` 既重現官方數字、接縫又 bit-safe。
證明見 `scripts/seed_from_finlab.py`:`build_curve(seed)` 與原 monorepo curve **全欄 max|diff| = 0**。

## 本地執行
```bash
uv venv .venv && uv pip install --python .venv/bin/python -r requirements.txt
python -m src.pipeline            # fetch(Yahoo)→ rebuild → metrics → export
python -m src.pipeline --no-fetch # 離線只重算(CI 重現)
python -m pytest -q               # 測試
```

## 測試(三層三節奏)
- **每 commit / PR(快, `ci.yml`)**:重生性(raw→curve 逐位元)、golden 錨點、look-ahead 不變量(證明 shift load-bearing)、資料 sanity(OHLC 自洽 / 無壞 tick / MOVE 新鮮度)。
- **改策略才跑(`audit-on-change.yml`)**:CPCV+PBO / 參數 sweep(策略凍結期間不觸發;目前為 placeholder,解凍時 port)。
- **每日(`daily.yml`)**:跑完整管線 + 快測,綠燈才 commit/push(失敗不部署)。

## 部署(Cloudflare Pages)
公開站 → CF 後台把本 repo 接上 Pages(Git 整合),輸出目錄 `site/`,每次 push 自動 build/deploy。**CI 不需要任何 token。**

## 外部稽核(需要時)
本專案日常不碰 finlab。要做**外部交叉稽核**(例如重跑 CPCV+PBO、或驗證 seed 沒走樣)時,
在 finlab monorepo 端跑 `scripts/seed_from_finlab.py` 重新匯出 seed 並對拍,即可獨立驗證數字。

## 誠實話(數字會怎麼動)
- 頁面 **Tier-1**(NAV/曝險圖、訊號卡、IS/OOS/全期 window 統計、instrument 對照)= 即時算,每天自動更新。
- 頁面 **Tier-2**(敘述段 PBO / bootstrap / 參數網格)= 一次性稽核快照(標 as-of),改策略才更新。
- 凍結策略下指標仍會因**開口窗延伸**漂移:全期 Sharpe 幾乎不動、滾動 1 年會晃、MDD 單向棘輪。
  漂移**多是窗口機制非 alpha 變化**;全期 Sharpe **偵測不到衰退**(被歷史錨住),滾動窗會反應但吵且 underpowered。

## License
MIT(見 `LICENSE`)。回測數字僅供研究,非投資建議。
