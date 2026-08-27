#!/usr/bin/env python3
"""
README.md 의 25인 표를 docs/index.html 에서 다시 만든다.

같은 25명을 한 줄로 설명하는 문장이 사이트와 README 두 곳에 따로 쓰이면서
25명 중 24명이 서로 다른 말을 하게 됐다. 정본은 사이트(`docs/index.html` 의
DOMAINS/PEOPLE 배열)로 두고, README 표는 거기서 찍어 낸다. README 는 정본이
아니므로 표를 직접 고치지 말고 이 스크립트를 다시 돌린다.

    python3 scripts/sync_docs.py          # 다시 만들어 저장
    python3 scripts/sync_docs.py --check  # 어긋났으면 exit 1 (저장하지 않음)
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "docs" / "index.html"
README = ROOT / "README.md"

HEAD = "| 영역 | 전문가 | 한 줄로 말하면 |"
SEP = "|---|---|---|"


def build_table() -> str:
    html = INDEX.read_text(encoding="utf-8")
    domains = re.findall(r"\{name:'([^']+)',\s*en:'[^']*',\s*c:'[^']*'\}", html)
    people = re.findall(r"\{d:(\d+),kr:'([^']+)',s:'[^']*',en:'[^']*',p:'([^']+)'\}", html)
    if len(domains) != 5 or len(people) != 25:
        sys.exit(f"docs/index.html 파싱 실패. 영역 {len(domains)}개, 인물 {len(people)}명")
    rows, prev = [HEAD, SEP], None
    for d, kr, p in people:
        dom = domains[int(d)]
        rows.append(f"| {dom if dom != prev else ''} | {kr} | {p.rstrip('.')} |")
        prev = dom
    return "\n".join(rows)


def main() -> None:
    check = "--check" in sys.argv
    t = README.read_text(encoding="utf-8")
    m = re.search(r"^\| 영역 \|.*?(?=\n\n)", t, re.S | re.M)
    if not m:
        sys.exit("README.md 에서 25인 표를 찾지 못했습니다.")

    table = build_table()
    if m.group(0) == table:
        print("README.md 25인 표 이미 최신입니다.")
        return
    if check:
        sys.exit("README.md 표가 docs/index.html 과 어긋났습니다. scripts/sync_docs.py 를 실행하세요.")

    README.write_text(t[:m.start()] + table + t[m.end():], encoding="utf-8")
    print("README.md 25인 표 갱신 완료 (정본: docs/index.html)")


if __name__ == "__main__":
    main()
