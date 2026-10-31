#!/usr/bin/env python3
"""헤드리스 실행 기록(stream-json)에서 위원 원답을 뽑아 CASES.md 6-2 형식으로 적는다.

    python3 scripts/extract_answers.py OUT/01 > OUT/01/answers.md
    python3 scripts/extract_answers.py OUT/01 --all     # 라운드 2(교차심문, 반대 변호)까지

OUT/NN/turn-*.jsonl 을 읽는다(scripts/run_case.py 가 남긴 것). 위원 호출(Agent, 또는 같은
위원을 이어 부르는 SendMessage) 하나가 한 답이다. 그 호출 동안 위원이 낸 마지막 글을 답으로 본다.
단계는 위원의 첫 호출을 "라운드 1"로, 이후 호출은 프롬프트 내용으로 "재질문", "라운드 3",
"라운드 2"로 가른다. 호출마다 단계, 위원, 모델, 글자 수를 stderr 로 찍는다.
"""
import argparse
import gzip
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def slug_names(repo):
    """SKILL.md 이름 대응표("소크라테스=socrates, ...")에서 슬러그 -> 표시 이름."""
    names = {}
    for m in re.finditer(r"([가-힣 ]+?)=([a-z-]+)", (Path(repo) / "SKILL.md").read_text(encoding="utf-8")):
        names.setdefault(m.group(2), m.group(1).strip())
    return names


def _result_text(content):
    if isinstance(content, str):
        return content
    return "\n".join(x.get("text", "") for x in content or [] if isinstance(x, dict))


def calls_of(case_dir):
    calls, by_id, task_orig, active, last, model = [], {}, {}, {}, {}, {}
    sync = {}
    turns = sorted(list(Path(case_dir).glob("turn-*.jsonl")) + list(Path(case_dir).glob("turn-*.jsonl.gz")),
                   key=lambda p: int(p.name.split("-")[1].split(".")[0]))
    for f in turns:
        raw = gzip.open(f, "rt", encoding="utf-8").read() if f.suffix == ".gz" else f.read_text(encoding="utf-8")
        for line in raw.splitlines():
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            t, parent = ev.get("type"), ev.get("parent_tool_use_id")
            msg = ev.get("message") or {}
            if t == "assistant" and not parent:
                for c in msg.get("content", []):
                    if c.get("type") != "tool_use":
                        continue
                    inp = c.get("input", {})
                    if c["name"] in ("Agent", "Task"):
                        d = {"id": c["id"], "kind": "agent", "prompt": inp.get("prompt", ""),
                             "slug": inp.get("subagent_type", "?").split(":")[-1]}
                    elif c["name"] == "SendMessage":
                        d = {"id": c["id"], "kind": "send", "prompt": inp.get("message", "") or "",
                             "slug": inp.get("to", "?")}
                    else:
                        continue
                    calls.append(d)
                    by_id[c["id"]] = d
            elif t == "system" and ev.get("subtype") == "task_started":
                tid, cid = ev.get("task_id"), ev.get("tool_use_id")
                if cid in by_id and by_id[cid]["kind"] == "agent":
                    task_orig[tid] = cid
                orig = task_orig.get(tid)
                if orig:
                    active[orig] = cid
                    if by_id.get(cid, {}).get("kind") == "send":
                        by_id[cid]["slug"] = by_id[orig]["slug"]
            elif t == "assistant" and parent:
                cid = active.get(parent, parent)
                texts = [c["text"] for c in msg.get("content", [])
                         if c.get("type") == "text" and c["text"].strip()]
                if texts:
                    last[cid] = "\n".join(texts)
                    model[cid] = msg.get("model", "?")
            elif t == "user" and not parent and isinstance(msg.get("content"), list):
                for c in msg["content"]:
                    if c.get("type") == "tool_result":
                        s = _result_text(c.get("content"))
                        if "[Subagent hand-back]" in s:
                            body = re.sub(r"^.*?The report follows:\n", "", s, flags=re.S)
                            body = re.sub(r"^  ", "", body, flags=re.M)
                            # 끝에 붙는 실행 정보(agentId, <usage>)는 원답이 아니다.
                            sync[c["tool_use_id"]] = re.split(r"\n(?:agentId:|<usage>)", body)[0]
    for d in calls:
        d["answer"] = (last.get(d["id"]) or sync.get(d["id"], "")).strip()
        d["model"] = model.get(d["id"], "-")
    return calls


def stage_of(d, seen):
    p = d["prompt"]
    if d["kind"] == "agent" and d["slug"] not in seen:
        return "라운드 1"
    if re.search(r"\(8\)|실패한다면|If it fails|Round 3|라운드 3", p):
        return "라운드 3"
    if re.search(r"직답만|다시 받|새 선택지|다시 묻|re-ask|Re-ask|answer again", p):
        return "재질문"
    return "라운드 2"


def extract(case_dir, case_no, repo=ROOT, show_all=False, log=sys.stderr):
    names = slug_names(repo)
    seen, out = set(), [f"## 사례 {int(re.sub(r'[^0-9]', '', str(case_no)) or 0)}\n"]
    for d in calls_of(case_dir):
        if d["slug"] not in names:
            # 위원이 아닌 호출(코디네이터가 도구를 시험한 general-purpose 호출 등)은 원답이 아니다.
            print(f"건너뜀 {d['slug']:22} prompt={len(d['prompt']):5}", file=log)
            continue
        stage = stage_of(d, seen)
        seen.add(d["slug"])
        print(f"{stage:6} {d['slug']:22} model={d['model']:18} prompt={len(d['prompt']):5} "
              f"answer={len(d['answer']):5}", file=log)
        if stage == "라운드 2" and not show_all:
            continue
        out += [f"### {names.get(d['slug'], d['slug'])} · {stage}", d["answer"], ""]
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser(description="실행 기록에서 위원 원답 뽑기")
    ap.add_argument("case_dir", help="run_case.py 결과 폴더 (OUT/NN)")
    ap.add_argument("--all", action="store_true", help="라운드 2 답도 넣는다")
    args = ap.parse_args()
    sys.stdout.write(extract(args.case_dir, Path(args.case_dir).name, ROOT, args.all))
    return 0


if __name__ == "__main__":
    sys.exit(main())
