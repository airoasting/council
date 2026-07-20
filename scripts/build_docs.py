#!/usr/bin/env python3
"""
docs/index.html 안에 박혀 있는 25인 에이전트 원문(PROMPTS 배열)을 agents/에서 다시 만든다.

웹사이트는 각 에이전트의 마크다운 전문을 index.html에 JSON으로 품고 있다. agents/를
고쳐도 이 배열을 갱신하지 않으면 사이트만 옛 내용을 계속 보여 준다. 그 어긋남을 없애려고
agents/를 유일한 원본으로 두고 배열을 통째로 다시 찍는다.

    python3 scripts/build_docs.py          # 다시 만들어 저장
    python3 scripts/build_docs.py --check  # 어긋났으면 exit 1 (저장하지 않음)

순서는 SKILL.md의 5개 영역 배치를 따른다. 사이트의 카드 순서가 스킬 문서의 소개 순서와
같아야 읽는 사람이 둘을 오갈 때 헷갈리지 않기 때문이다.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENTS = ROOT / "agents"
INDEX = ROOT / "docs" / "index.html"

# SKILL.md의 "25명의 전문가 (5개 영역 x 5)" 순서
ORDER = [
    "socrates", "aristotle", "marcus-aurelius", "lao-tzu", "alfred-adler",
    "sun-tzu", "carl-clausewitz", "niccolo-machiavelli", "yi-sunsin", "jeong-yakyong",
    "peter-drucker", "daniel-kahneman", "nassim-taleb", "clayton-christensen", "jim-collins",
    "elon-musk", "sam-altman", "dario-amodei", "demis-hassabis", "jensen-huang",
    "warren-buffett", "charlie-munger", "cathie-wood", "ray-dalio", "howard-marks",
]

PATTERN = re.compile(r"(const PROMPTS = )(\[.*?\])(;\n)", re.S)


def build_array() -> str:
    found = {p.stem for p in AGENTS.glob("*.md")}
    if found != set(ORDER):
        missing, extra = set(ORDER) - found, found - set(ORDER)
        sys.exit(f"agents/ 와 ORDER 불일치. 빠짐={sorted(missing)} 남음={sorted(extra)}")
    prompts = [{"file": s, "md": (AGENTS / f"{s}.md").read_text(encoding="utf-8")} for s in ORDER]
    return json.dumps(prompts, ensure_ascii=False)


def main() -> None:
    check = "--check" in sys.argv
    html = INDEX.read_text(encoding="utf-8")
    m = PATTERN.search(html)
    if not m:
        sys.exit("docs/index.html 에서 PROMPTS 배열을 찾지 못했습니다.")

    new_array = build_array()
    if m.group(2) == new_array:
        print("docs/index.html 이미 최신입니다.")
        return
    if check:
        sys.exit("docs/index.html 이 agents/ 와 어긋났습니다. scripts/build_docs.py 를 실행하세요.")

    INDEX.write_text(html[:m.start(2)] + new_array + html[m.end(2):], encoding="utf-8")
    print(f"docs/index.html 갱신 완료 ({len(ORDER)}개 에이전트)")


if __name__ == "__main__":
    main()
