#!/usr/bin/env python3
"""사례 하나를 헤드리스로 끝까지 돌린다 (tests/CASES.md 2-2 방법 C).

    python3 scripts/run_case.py tests/cases/01.md --out tests/runs/release-2026-10-31
    python3 scripts/run_case.py tests/cases/01.md --out /tmp/x --plugin-dir .   # 저장소 작업본으로

하는 일
1. 사례 파일의 입력(prefix + 입력 전문)을 `claude -p`로 보낸다. 작업 폴더는 OUT/NN/cwd(빈 폴더)다.
2. 코디네이터가 질문으로 차례를 끝내면, 질문 내용을 보고 사례 파일 "사용자 응답 대본"의
   답(선택지 확인 / 관문 질문 / 기록 묻기)을 골라 `--resume`으로 이어 보낸다. 종합이 나오면 멈춘다.
3. OUT/NN/ 에 turn-N.jsonl(전체 이벤트), turn-N.text.md(그 차례의 마지막 글),
   final.md(종합), answers.md(위원 원답, CASES.md 6-2 형식), log.json(차례별 시간과 비용)을 남긴다.

채점은 따로 한다.
    python3 scripts/check_run.py OUT/NN/final.md --case tests/cases/NN.md --answers OUT/NN/answers.md \
        --options "<소집 공개의 가를 선택지>"
"""
import argparse
import collections
import gzip
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from extract_answers import extract  # noqa: E402
from check_run import parse_case  # noqa: E402

# 기록은 쓰지 않는다(Write 없음). 사례 대본도 "기록 없이 진행"이다.
ALLOWED = "Agent,Task,Read,Glob,Grep,ToolSearch,SendMessage,Bash(git rev-parse:*)"
VERDICT = ("AI ROASTING 종합 의견", "AI ROASTING Verdict")
GATE = ("빠졌다고", "missing", "left out")
RECORD = ("COUNCIL_LOG", "기록할까", "기록해 둘까", "기록을 남길까", "save this", "log this", "record this")


def script_replies(case_text):
    """'사용자 응답 대본' 표에서 (선택지 확인, 관문 질문, 기록 묻기) 답을 읽는다."""
    want = {"선택지 확인": None, "관문 질문": None, "기록 묻기": None}
    sec = case_text.split("## 사용자 응답 대본", 1)[-1].split("\n## ", 1)[0]
    for line in sec.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 2:
            for k in want:
                if cells[0].startswith(k) and want[k] is None:
                    want[k] = cells[1]
    missing = [k for k, v in want.items() if v is None]
    if missing:
        raise SystemExit(f"사용자 응답 대본에 없는 줄: {', '.join(missing)}")
    return want["선택지 확인"], want["관문 질문"], want["기록 묻기"]


def asks(text):
    """차례 끝이 질문인가. 종합 끝의 "기록은 남기지 않았습니다" 같은 안내는 질문이 아니다."""
    tail = text.strip()[-300:]
    return bool(re.search(r"[?？]\s*\**\s*$|까요\??\s*\**\s*$|주세요\.?\s*\**\s*$", tail))


def pick(text, opt_r, gate_r, rec_r):
    tail = text[-1500:]
    asks_record = any(r in tail for r in RECORD)
    names_options = any(k in tail for k in ("선택지", "options", "Options"))
    if asks_record and names_options:
        return opt_r  # 0단계 확인은 선택지와 기록 여부를 한 번에 묻는다
    if any(g in tail for g in GATE):
        return gate_r
    if asks_record:
        return rec_r
    return opt_r


def run(prompt, work, out, turn, extra, session=None):
    cmd = ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose",
           "--allowedTools", ALLOWED, *extra]
    if session:
        cmd += ["--resume", session]
    t0 = time.time()
    p = subprocess.run(cmd, cwd=work, capture_output=True, text=True, timeout=3600)
    dt = time.time() - t0
    (out / f"turn-{turn}.jsonl").write_text(p.stdout)
    if p.stderr:
        (out / f"turn-{turn}.stderr").write_text(p.stderr)
    sid, final, usage = session, "", {}
    for line in p.stdout.splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "system" and ev.get("session_id"):
            sid = ev["session_id"]
        if ev.get("type") == "result":
            final = ev.get("result", "") or final
            usage = {k: ev.get(k) for k in ("duration_ms", "total_cost_usd", "num_turns")}
            sid = ev.get("session_id", sid)
    (out / f"turn-{turn}.text.md").write_text(final)
    return sid, final, round(dt), usage


def scrub(raw):
    """공개 저장소에 둘 기록에서 이 컴퓨터의 정보를 뺀다. 시작 이벤트(설치된 플러그인, MCP 서버,
    도구 목록이 든 system/init)는 버리고, 홈 폴더 경로는 ~ 로 바꾼다."""
    home = str(Path.home())
    keep = []
    for line in raw.splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "system" and ev.get("subtype") == "init":
            continue
        keep.append(line.replace(home, "~"))
    return "\n".join(keep) + "\n"


def tool_summary(out):
    """메인 세션의 도구 호출 수와, 띄운 서브에이전트 이름(subagent_type)별 호출 수."""
    tools, agents = collections.Counter(), collections.Counter()
    for f in sorted(out.glob("turn-*.jsonl")):
        for line in f.read_text().splitlines():
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("type") != "assistant" or ev.get("parent_tool_use_id"):
                continue
            for c in (ev.get("message") or {}).get("content", []):
                if c.get("type") == "tool_use":
                    tools[c["name"]] += 1
                    if c["name"] in ("Agent", "Task"):
                        agents[c.get("input", {}).get("subagent_type", "?")] += 1
    return {"tools": dict(tools), "subagent_types": dict(agents)}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("case", help="사례 파일 (tests/cases/NN.md)")
    ap.add_argument("--out", required=True, help="결과 폴더. OUT/NN/ 아래에 남긴다")
    ap.add_argument("--plugin-dir", help="설치본 대신 이 폴더를 플러그인으로 올린다(claude --plugin-dir)")
    ap.add_argument("--max-turns", type=int, default=6)
    args = ap.parse_args()

    case_path = Path(args.case)
    case = parse_case(case_path)
    opt_r, gate_r, rec_r = script_replies(case_path.read_text(encoding="utf-8"))
    num = case_path.stem
    out = Path(args.out) / num
    work = out / "cwd"
    work.mkdir(parents=True, exist_ok=True)
    extra = ["--plugin-dir", str(Path(args.plugin_dir).resolve())] if args.plugin_dir else []

    prompt = (case["prefix"] + " " + case["input"]).strip()
    log = []
    sid, final, dt, usage = run(prompt, work, out, 0, extra)
    log.append({"turn": 0, "sent": prompt[:60], "seconds": dt, **usage})
    verdict = final if any(h in final for h in VERDICT) else ""
    turn = 0
    while turn < args.max_turns:
        if verdict:
            if not (any(r in final[-800:] for r in RECORD) and asks(final)):
                break
            reply = rec_r
        else:
            reply = pick(final, opt_r, gate_r, rec_r)
        turn += 1
        sid, final, dt, usage = run(reply, work, out, turn, extra, session=sid)
        log.append({"turn": turn, "sent": reply, "seconds": dt, **usage})
        if verdict:
            break
        if any(h in final for h in VERDICT):
            verdict = final

    (out / "final.md").write_text(verdict or final)
    # 소집 공개의 "가를 선택지"(채점 때 --options 로 넘긴다)
    convene = (out / "turn-0.text.md").read_text().replace("**", "")
    m = re.search(r"(?:가를 선택지|Options?(?: to decide(?: between)?)?)\s*[:：]\s*(.+)", convene)
    (out / "options.txt").write_text(m.group(1).strip() if m else "")
    (out / "answers.md").write_text(extract(out, num, ROOT, show_all=True))
    (out / "log.json").write_text(json.dumps(log, ensure_ascii=False, indent=2))
    (out / "tools.json").write_text(json.dumps(tool_summary(out), ensure_ascii=False, indent=2))
    for f in out.glob("turn-*.jsonl"):  # 원본 이벤트는 압축해 남긴다(과정 기준 감사용)
        with gzip.open(str(f) + ".gz", "wt", encoding="utf-8") as dst:
            dst.write(scrub(f.read_text(encoding="utf-8")))
        f.unlink()
    secs = sum(x["seconds"] for x in log)
    # --resume 세션의 total_cost_usd 는 누적값이라 더하지 않고 마지막 값을 쓴다.
    cost = max((x.get("total_cost_usd") or 0 for x in log), default=0)
    print(f"사례 {num}: 차례 {len(log)}, {secs}초(사용자 대기 없음), 비용 약 ${cost:.2f}, "
          + ("종합 있음" if verdict else "종합 없음"))
    return 0 if verdict else 1


if __name__ == "__main__":
    sys.exit(main())
