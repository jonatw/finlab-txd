"""專案運維/呈現設定(策略本身凍結;這些不是策略旋鈕)。"""

# TXD paper-lane 起算日:從這天開始把後續真實市場資料當「實單」追蹤(對照回測期望帶)。
PAPER_DEPLOY_DATE = "2026-06-19"
PAPER_STAGE = "PAPER"          # RESEARCH → PAPER(開始紙上追蹤)
PAPER_LANE_HEALTH = "GREEN"

# P/C 反向擇時 paper-lane 起算日(平行觀察訊號,#133;不混入 TXD 部署曲線)。
PCR_PAPER_DEPLOY_DATE = "2026-06-22"
