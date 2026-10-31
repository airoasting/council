#!/usr/bin/env python3
"""run_case.py 결과 폴더를 채점해 CASES.md 6-1 양식의 두 표를 찍는다.

    python3 scripts/run_table.py tests/runs/release-2026-10-31 [01 02 03 04 05]

사례마다 OUT/NN/final.md, answers.md, options.txt(소집 공개의 가를 선택지), log.json 을 읽는다.
check_run.py 의 판정을 기준 ID별로 모아 "통과 / 실패 / 확인 / 경고 / 해당 없음"으로 적는다.
"확인"(REVIEW)은 사람이 보고 통과나 실패로 바꿔 적는다. 시간은 사용자 응답 대기를 뺀 실행 시간,
비용은 --resume 세션의 누적값(log.json 마지막 차례)이다.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# CASES.md 4-3의 수동 필수 기준. 사람이 읽고 채운다. 다 채우기 전에는 합격을 찍지 않는다.
MANUAL = [("S8", "칸끼리 같은 결론·기한·사실"), ("S9", "멈춤 신호와 판단 규칙이 반대로 다루지 않음"),
          ("S11", "첫 행동이 확인의 첫걸음"), ("S13", "반대 변론 표기와 실행 방식 차이"),
          ("S18", "변론 뒤 만장일치면 남은 위험")]
WORD = {"FAIL": "실패", "REVIEW": "확인", "WARN": "경고", "PASS": "통과", "SKIP": "해당 없음"}


def grade(out, num):
    d = out / num
    cmd = [sys.executable, str(ROOT / "scripts" / "check_run.py"), "--case", str(ROOT / "tests" / "cases" / f"{num}.md"),
           "--answers", str(d / "answers.md"), str(d / "final.md")]
    opts = d / "options.txt"
    if opts.exists() and opts.read_text().strip():
        cmd[2:2] = ["--options", opts.read_text().strip()]
    res = {}
    for line in subprocess.run(cmd, capture_output=True, text=True).stdout.splitlines():
        m = re.match(r"^(PASS|FAIL|WARN|REVIEW|SKIP)\s+(\S+)\s", line)
        if m:
            res.setdefault(m.group(2), []).append(m.group(1))
    return res


def cell(sts):
    if not sts:
        return "해당 없음"
    for k in ("FAIL", "REVIEW", "WARN"):
        if k in sts:
            return WORD[k]
    return "해당 없음" if all(s == "SKIP" for s in sts) else "통과"


def main():
    out = Path(sys.argv[1])
    nums = sys.argv[2:] or sorted(p.name for p in out.iterdir() if p.is_dir() and p.name.isdigit())
    grades = {n: grade(out, n) for n in nums}
    print("| 사례 | 결과 | 자동 실패 | 확인할 것 | 시간(분) | 비용(달러, 누적) |")
    print("|---|---|---|---|---|---|")
    for n in nums:
        log = json.loads((out / n / "log.json").read_text())
        secs = sum(x["seconds"] for x in log)
        cost = max((x.get("total_cost_usd") or 0 for x in log), default=0)
        fails = [k for k, v in grades[n].items() if "FAIL" in v]
        revs = [k for k, v in grades[n].items() if "REVIEW" in v and "FAIL" not in v]
        verdict = "불합격" if fails else "판정 전(확인과 수동 기준)"
        print(f"| {n} | {verdict} | {', '.join(fails) or '없음'} | {', '.join(revs) or '없음'} | "
              f"{secs / 60:.1f} | {cost:.2f} |")
    print()
    keys = []
    for n in nums:
        for k in grades[n]:
            if k not in keys:
                keys.append(k)
    print("| 기준 | " + " | ".join(nums) + " |")
    print("|---|" + "---|" * len(nums))
    for k in keys:
        print(f"| {k} | " + " | ".join(cell(grades[n].get(k)) for n in nums) + " |")
    for k, name in MANUAL:
        print(f"| {k} {name} | " + " | ".join("판정 전" for _ in nums) + " |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
