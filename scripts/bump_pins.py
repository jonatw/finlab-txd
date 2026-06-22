"""把 requirements.txt 的 ==pin 改寫成『目前環境實裝版本』。
dep-bump workflow 先把所有套件 pip install -U 到最新,再呼叫本檔把 pin 對齊實裝版。
只動 requirements.txt 既有的那幾行(保留順序/註解),找不到的套件原樣保留。"""
import re
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

REQ = Path(__file__).resolve().parents[1] / "requirements.txt"


def main() -> int:
    out, changed = [], []
    for ln in REQ.read_text().splitlines():
        m = re.match(r"^\s*([A-Za-z0-9_.\-]+)==([^\s#]+)", ln)
        if not m:
            out.append(ln)
            continue
        name, old = m.group(1), m.group(2)
        try:
            new = version(name)
        except PackageNotFoundError:
            out.append(ln)
            continue
        out.append(f"{name}=={new}")
        if new != old:
            changed.append(f"{name} {old} → {new}")
    REQ.write_text("\n".join(out) + "\n")
    print("dep changes:", "; ".join(changed) if changed else "(none)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
