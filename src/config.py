"""專案運維/呈現設定(策略本身凍結;這些不是策略旋鈕)。"""

# TXD paper-lane 起算日:從這天開始把後續真實市場資料當「實單」追蹤(對照回測期望帶)。
# 對齊真實新倉位起點:exposure 在 6/17 由 0(空手)→ 2x,故 paper-lane 從 6/17 起算(原 6/19 漏掉前 2 天)。
PAPER_DEPLOY_DATE = "2026-06-17"
PAPER_STAGE = "PAPER"          # RESEARCH → PAPER(開始紙上追蹤)
PAPER_LANE_HEALTH = "GREEN"

# P/C 反向擇時 paper-lane 起算日(平行觀察訊號,#133;不混入 TXD 部署曲線)。
PCR_PAPER_DEPLOY_DATE = "2026-06-22"
