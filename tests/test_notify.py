"""notify_webhook 冒煙測試:無變化 / WEBHOOK 未設時須乾淨退出(不送、不崩)。"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_notify_exits_clean_without_webhook():
    env = {k: v for k, v in os.environ.items() if k not in ("WEBHOOK", "WEBHOOK_SECRET")}
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "notify_webhook.py")],
        capture_output=True, text=True, env=env, timeout=30,
    )
    assert r.returncode == 0, r.stderr
    assert ("unchanged" in r.stdout) or ("skip" in r.stdout), r.stdout
