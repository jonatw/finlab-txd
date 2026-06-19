"""health 監控:bootstrap 帶確定性 + 排序 + DD 欄位 sanity。"""
import numpy as np
from src.health import block_bootstrap_paths, HORIZON, NBOOT, BLOCK, SEED


def test_bootstrap_deterministic():
    r = np.array([0.01, -0.02, 0.005, 0.0, 0.03, -0.01] * 50, dtype=float)
    a = block_bootstrap_paths(r, HORIZON, NBOOT, BLOCK, SEED)
    b = block_bootstrap_paths(r, HORIZON, NBOOT, BLOCK, SEED)
    assert np.array_equal(a, b), "同 seed 應逐位元相同(CI 重現)"


def test_band_ordering(curve):
    r = curve["pnl"].astype(float).values
    paths = block_bootstrap_paths(r, HORIZON, NBOOT, BLOCK, SEED)
    p5, p50, p95 = np.percentile(paths, [5, 50, 95], axis=0)
    assert (p5 <= p50).all() and (p50 <= p95).all(), "百分位帶須 p5<=p50<=p95"
    assert paths.shape == (NBOOT, HORIZON)


def test_dd_sane(curve):
    nav = curve["strategy"].astype(float)
    dd = nav / nav.cummax() - 1
    assert float(dd.min()) <= 0 and float(dd.iloc[-1]) <= 0, "回撤非正"
