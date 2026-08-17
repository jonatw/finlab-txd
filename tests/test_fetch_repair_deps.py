"""回歸測試 2026-08-17(issue 19):yfinance 1.6.0 的 repair 路徑改用 sklearn,
而 `[repair]` extra 的相依我們只裝了一半(有 scipy、沒 scikit-learn)。
yfinance 會把 ModuleNotFoundError **吞掉**、印 "1 Failed download" 並回空 DataFrame,
於是 _yf() 空轉 4 輪 backoff 後丟出 "empty result (Yahoo 可能擋下/壞掉)"
—— 把「我們少裝套件」謊報成「外部服務故障」,查了很久才找到真因。

守的是:缺 repair 相依時,_yf() 必須在【進重試迴圈之前】就以真正的 ModuleNotFoundError
失敗,而不是空轉 backoff 再嫁禍 Yahoo。

⚠️ CI 環境一定裝得齊 sklearn/scipy,所以這條路【只有】這支測試守得到 ——
其餘測試對「缺相依時訊息準不準」鑑別力是零。刪掉 src/fetch.py 那兩行明確 import,
只有這支會紅。
"""
import sys
from unittest import mock

import pandas as pd
import pytest

from src.fetch import _yf


def _fake_bars():
    idx = pd.to_datetime(["2026-08-14", "2026-08-15"])
    return pd.DataFrame(
        {"Open": [1.0, 2.0], "High": [1.0, 2.0], "Low": [1.0, 2.0], "Close": [1.0, 2.0]},
        index=idx,
    )


@pytest.mark.parametrize("missing", ["scipy", "sklearn"])
def test_missing_repair_dep_raises_real_error_before_any_download(missing):
    """缺相依 → 真正的 ModuleNotFoundError,且**一次 download 都沒發出**。

    `dl.assert_not_called()` 是這支的骨幹:它證明前置檢查跑在重試迴圈【之前】。
    若把 import 移進迴圈的 try(或整個拿掉),download 會被呼叫 → 這支就紅。
    """
    with mock.patch("yfinance.download") as dl:
        dl.side_effect = AssertionError("缺相依時不該走到 yf.download —— 前置檢查沒生效")
        with mock.patch.dict(sys.modules, {missing: None}):
            with pytest.raises(ModuleNotFoundError) as ei:
                _yf("^TWII", False, period="5d")
    assert missing in str(ei.value)
    dl.assert_not_called()


def test_control_deps_present_reaches_download():
    """負控:相依齊全時同一條路【必須】走到 yf.download。

    沒有這支,上面那兩支可能只是因為別的理由早退,看起來綠卻什麼都沒守到。
    """
    with mock.patch("yfinance.download", return_value=_fake_bars()) as dl:
        out = _yf("^TWII", False, period="5d")
    dl.assert_called_once()
    assert not out.empty
