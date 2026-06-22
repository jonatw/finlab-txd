"""把 requirements.txt 的 ==pin 改寫成『目前環境實裝版本』,並分類 major vs minor/patch。
dep-bump workflow 先把所有套件 pip install -U 到最新,再呼叫本檔把 pin 對齊實裝版。
只動 requirements.txt 既有的那幾行(保留順序/註解),找不到的套件原樣保留。

政策:任何套件 major 版號(第一段數字)上升 → has_major=true → workflow 改走 PR 等人 review;
否則(minor/patch)→ 自動 commit。輸出寫進 $GITHUB_OUTPUT 供 workflow 判斷。"""
import os
import re
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

REQ = Path(__file__).resolve().parents[1] / "requirements.txt"


def _major(v: str) -> int:
    try:
        return int(re.match(r"\d+", v).group())
    except (AttributeError, ValueError):
        return -1


def main() -> int:
    out, changed, majors = [], [], []
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
            changed.append(f"{name} {old} -> {new}")
            if _major(new) > _major(old):
                majors.append(f"{name} {old} -> {new}")
    REQ.write_text("\n".join(out) + "\n")

    has_major = bool(majors)
    summary = "; ".join(changed) if changed else "(none)"
    print("dep changes:", summary)
    if majors:
        print("MAJOR bumps (→ PR):", "; ".join(majors))
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a", encoding="utf-8") as f:
            f.write(f"has_changes={'true' if changed else 'false'}\n")
            f.write(f"has_major={'true' if has_major else 'false'}\n")
            f.write(f"changes={summary}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
