#!/usr/bin/env python3
"""
Validate the AI ROASTING 자문단 agent files against SKILL.md.

Catches the failure class that breaks dispatch: filename / name / SKILL slug
mismatches, missing sections, em dashes, and drift between the three places a
slug lives (agent files, the SKILL.md runtime lookup table, resolve_members.py).
Run from the package root:

    python3 scripts/validate_agents.py

Exit code 0 = all good (this is what the "25 Verified" badge stands on).
"""
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # 검사하느라 scripts/__pycache__ 를 남기지 않는다

ROOT = Path(__file__).resolve().parent.parent
AGENTS = ROOT / "agents"
SKILL = ROOT / "SKILL.md"

REQUIRED_SECTIONS = [
    "## 저는 누구인가",
    "## 제가 지키는 원칙",
    "## 제가 결론을 내리는 법",
    "## 제가 지어내지 않는 것",
]


def frontmatter(text):
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    return m.group(1) if m else ""


def field(fm, key):
    m = re.search(rf"^\s*{key}:\s*(.+)$", fm, re.M)
    return m.group(1).strip().strip('"') if m else None


def section(text, title):
    """'## {title}' 절의 본문. 없으면 None."""
    m = re.search(rf"^## {re.escape(title)}[^\n]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(1) if m else None


INTENTIONAL = re.compile(r"의도된 불일치|intentional-mismatch")


def _norm(s):
    return re.sub(r"[\s\"'“”‘’.,()*]", "", s or "")


def _cell(body, name):
    """고정 답 안의 '(n) 칸 이름. 값' 또는 '(n) 칸 이름: 값' 줄의 값."""
    m = re.search(rf"^\s*(?:\(\d+\)\s*)?{name}\s*[.:：]\s*(.+?)\s*$", body, re.M)
    return m.group(1).strip().rstrip(".").strip().strip('"“”') if m else None


def check_case_fixtures(labels_by_slug, name_to_slug, errors):
    """사례 파일의 고정 답과 하위 사례 표를 검사하고, 검사한 값의 수를 돌려준다."""
    checked = 0
    for case in sorted((ROOT / "tests" / "cases").glob("*.md")):
        text = case.read_text(encoding="utf-8")
        fm = frontmatter(text)
        rel = case.relative_to(ROOT)
        options = [o.strip() for o in (field(fm, "options") or "").split(" / ") if o.strip()]
        options += [x.strip() for x in re.findall(r"^extra_option:\s*(.+)$", fm, re.M)]
        opt_norm = {_norm(o) for o in options}

        def judge(where, name, kind, value, intentional):
            nonlocal checked
            slug = name_to_slug.get(name.strip())
            if not slug:
                errors.append(f"{rel}: {where} 위원 이름 '{name}' 을 슬러그로 풀지 못함")
                return
            if kind == "label":
                ok = value in labels_by_slug.get(slug, [])
                what = f"라벨 '{value}' (그 위원의 라벨: {' / '.join(labels_by_slug.get(slug, []))})"
            else:
                ok = _norm(value) in opt_norm
                what = f"직답 '{value}' (사례 선택지: {' / '.join(options)})"
            checked += 1
            if intentional and ok:
                errors.append(f"{rel}: {where} {name} 의 {what} 이 '의도된 불일치'인데 실제로는 맞음")
            elif not intentional and not ok:
                errors.append(f"{rel}: {where} {name} 의 {what} 이 어긋남 "
                              "(의도한 것이면 '의도된 불일치' 표시)")

        # ```fixture 블록. 바로 위의 '### 고정 답: 이름' 제목이 위원을 정한다.
        for m in re.finditer(r"^#{2,4}[ \t]*고정 답:[ \t]*([^\n(]+?)[ \t]*(\([^\n]*\))?[ \t]*\n"
                             r"((?:(?!```)[^\n]*\n)*?)```fixture\n(.*?)^```", text, re.M | re.S):
            name, note, between, body = m.group(1), m.group(2) or "", m.group(3), m.group(4)
            intentional = bool(INTENTIONAL.search(note + between))
            label, answer = _cell(body, "(?:최종 )?(?:판정 )?라벨"), _cell(body, "(?:최종 )?직답")
            if label is None or answer is None:
                errors.append(f"{rel}: 고정 답 '{name}' 에 판정 라벨이나 직답 줄이 없음")
                continue
            judge("고정 답", name, "label", label, intentional)
            if options:
                judge("고정 답", name, "answer", answer, intentional)

        # 하위 사례 표: | 하위 사례 | 위원 | 칸 | 바꿔 줄 값 | 비고 |
        for row in re.findall(r"^\|([^\n]+)\|[ \t]*$", text, re.M):
            cols = [c.strip() for c in row.split("|")]
            if len(cols) < 4 or not re.search(r"판정 라벨|라벨|직답", cols[2]) or cols[0].startswith("하위"):
                continue
            kind = "label" if "라벨" in cols[2] else "answer"
            if kind == "answer" and not options:
                continue
            note = cols[4] if len(cols) > 4 else ""
            judge(f"하위 사례 {cols[0]}", cols[1], kind, cols[3].strip('"“”'), bool(INTENTIONAL.search(note)))
    return checked


def main():
    errors = []
    notes = []
    agent_files = sorted(AGENTS.glob("*.md"))
    slugs = {f.stem for f in agent_files}

    if len(agent_files) != 25:
        errors.append(f"expected 25 agents, found {len(agent_files)}")

    skill_text = SKILL.read_text(encoding="utf-8") if SKILL.exists() else ""

    labels_by_slug = {}
    for f in agent_files:
        text = f.read_text(encoding="utf-8")
        fm = frontmatter(text)
        slug = f.stem

        name = field(fm, "name")
        if name != slug:
            errors.append(f"{f.name}: name '{name}' != filename '{slug}'")

        if field(fm, "figure") is None:
            errors.append(f"{f.name}: missing council.figure")

        if f"`{slug}`" not in skill_text:
            errors.append(f"{f.name}: slug '{slug}' not referenced in SKILL.md")

        for sec in REQUIRED_SECTIONS:
            if sec not in text:
                errors.append(f"{f.name}: missing section '{sec}'")

        if "—" in text:
            errors.append(f"{f.name}: contains em dash")

        # 형식 점검(라운드 1 직후 점검 2번)과 check_run.py 의 라벨 누출 검사는
        # "제가 결론을 내리는 법"의 '- 라벨. 설명' 줄 셋을 정본으로 쓴다.
        verdict = section(text, "제가 결론을 내리는 법")
        if verdict is not None:
            labels = [m.group(1) for m in re.finditer(r"^-\s+\**(.+?)\**\.(?:\s|$)", verdict, re.M)]
            labels_by_slug[slug] = labels
            if len(labels) != 3:
                errors.append(f"{f.name}: 판정 라벨이 {len(labels)}개 (셋이어야 함): {labels}")

    # SKILL.md runtime lookup table (Korean name = slug): every slug must be
    # real, and all 25 must appear. This is the table the coordinator dispatches
    # from, so drift here silently breaks --members.
    table_line = next(
        (ln for ln in skill_text.splitlines() if "소크라테스=socrates" in ln), ""
    )
    if not table_line:
        errors.append("SKILL.md lookup table line not found (anchor '소크라테스=socrates')")
    table_slugs = set(re.findall(r"=([a-z]+(?:-[a-z]+)*)", table_line))
    for s in table_slugs - slugs:
        errors.append(f"SKILL.md lookup table maps to unknown slug '{s}'")
    for s in slugs - table_slugs:
        errors.append(f"SKILL.md lookup table is missing slug '{s}'")

    # resolve_members.py must carry the same 25 slugs (no drift with the table).
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        import resolve_members  # noqa: E402

        if set(resolve_members.SLUGS) != slugs:
            extra = set(resolve_members.SLUGS) - slugs
            missing = slugs - set(resolve_members.SLUGS)
            errors.append(
                f"resolve_members.py slugs drift: extra={sorted(extra)} missing={sorted(missing)}"
            )
    except Exception as e:  # noqa: BLE001
        errors.append(f"could not import resolve_members.py: {e}")

    # 문서가 에이전트 섹션을 옛 이름으로 가리키면 dispatch 프롬프트가 없는 제목을
    # 찾게 된다. 섹션 제목을 바꾸고 SKILL.md 를 못 고친 사고가 실제로 났다.
    RENAMED = {
        "결정 규칙": "제가 결론을 내리는 법",
        "환각 방지 규칙": "제가 지어내지 않는 것",
        "시그니처 질문": "제가 늘 묻는 것",
        "분석 순서": "제가 따져 보는 순서",
        "방에 들어서는 자세": "제가 먼저 하는 일",
    }
    for doc in ("SKILL.md", "README.md"):
        dt = (ROOT / doc).read_text(encoding="utf-8") if (ROOT / doc).exists() else ""
        for old, now in RENAMED.items():
            if old in dt:
                errors.append(f"{doc}: refers to renamed agent section '{old}' (now '{now}')")

    # 25인 한 줄 설명은 docs/index.html 이 정본이고 README 표는 거기서 찍어 낸다.
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        import sync_docs  # noqa: E402

        rt = (ROOT / "README.md").read_text(encoding="utf-8")
        m = re.search(r"^\| 영역 \|.*?(?=\n\n)", rt, re.S | re.M)
        if not m:
            errors.append("README.md: 25인 표를 찾지 못했습니다")
        elif m.group(0) != sync_docs.build_table():
            errors.append("README.md 표가 docs/index.html 과 어긋남 (scripts/sync_docs.py 실행)")
    except SystemExit as e:  # noqa: PERF203
        errors.append(f"sync_docs.py: {e}")
    except Exception as e:  # noqa: BLE001
        errors.append(f"could not check README table: {e}")

    # 저장소 문서 전체에서 em dash 0. (이 파일의 검사 리터럴만 예외)
    for doc in (sorted(ROOT.glob("*.md")) + sorted((ROOT / "docs").glob("*.md"))
                + sorted((ROOT / "references").glob("*.md")) + sorted((ROOT / "tests").glob("*.md"))
                + sorted((ROOT / "tests" / "cases").glob("*.md"))):
        if "—" in doc.read_text(encoding="utf-8"):
            errors.append(f"{doc.relative_to(ROOT)}: contains em dash")

    # 대립극은 --duo 의 유일한 출처다. 25명을 다 덮지 못하면 못 쓰는 사람이 생긴다.
    duo_line = next((ln for ln in skill_text.splitlines()
                     if " / " in ln and "socrates" in ln), "")
    if not duo_line:
        errors.append("SKILL.md: 대립극 줄을 찾지 못했습니다")
    else:
        paired = {x.strip() for pair in duo_line.split("·") for x in pair.split("/")}
        for s in sorted(slugs - paired):
            errors.append(f"SKILL.md 대립극에 '{s}' 가 없어 --duo 로 못 부릅니다")
        for s in sorted(paired - slugs):
            errors.append(f"SKILL.md 대립극에 알 수 없는 슬러그 '{s}'")

    # (a) README 배지의 Version 과 plugin.json 의 version 이 같아야 한다.
    try:
        pv = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")).get("version")
    except Exception as e:  # noqa: BLE001
        pv = None
        errors.append(f".claude-plugin/plugin.json 을 읽지 못했습니다: {e}")
    readme_text = (ROOT / "README.md").read_text(encoding="utf-8") if (ROOT / "README.md").exists() else ""
    badge = re.search(r"badge/Version-([0-9]+(?:\.[0-9]+)*)-", readme_text)
    if not badge:
        errors.append("README.md: Version 배지를 찾지 못했습니다")
    elif pv and badge.group(1) != pv:
        errors.append(f"README.md Version 배지 {badge.group(1)} != plugin.json version {pv}")

    # (b) 전문가 선정 4번의 세 기울기 목록이 25명을 정확히 한 번씩 덮어야 한다.
    sel = section(skill_text, "전문가 선정") or ""
    tilt_lines = re.findall(r"^\s*-\s*([^:`\n]+):\s*((?:`[a-z-]+`(?:,\s*)?)+)\s*$", sel, re.M)
    if len(tilt_lines) != 3:
        errors.append(f"SKILL.md 전문가 선정: 기울기 목록이 {len(tilt_lines)}줄 (셋이어야 함)")
    tilted = [s for _, ln in tilt_lines for s in re.findall(r"`([a-z-]+)`", ln)]
    for s in sorted({x for x in tilted if tilted.count(x) > 1}):
        errors.append(f"SKILL.md 전문가 선정: '{s}' 가 기울기 목록에 두 번 이상 나옴")
    for s in sorted(slugs - set(tilted)):
        errors.append(f"SKILL.md 전문가 선정: '{s}' 가 기울기 목록에 없음")
    for s in sorted(set(tilted) - slugs):
        errors.append(f"SKILL.md 전문가 선정: 알 수 없는 슬러그 '{s}'")

    # (c) 트라이어드 표의 슬러그가 모두 실제 슬러그이고, 줄마다 셋이며, 본문의 개수와 맞아야 한다.
    tri = section(skill_text, "사전 정의 트라이어드") or ""
    rows = re.findall(r"^\|\s*`([a-z-]+)`[^|]*\|\s*([^|]+?)\s*\|", tri, re.M)
    if not rows:
        errors.append("SKILL.md: 트라이어드 표를 찾지 못했습니다")
    for name, cell in rows:
        members = [x.strip() for x in cell.split("+")]
        if len(members) != 3:
            errors.append(f"SKILL.md 트라이어드 '{name}': 위원이 {len(members)}명")
        for s in members:
            if s not in slugs:
                errors.append(f"SKILL.md 트라이어드 '{name}': 알 수 없는 슬러그 '{s}'")
    count = re.search(r"아래\s*(\d+)개", tri)
    if count and int(count.group(1)) != len(rows):
        errors.append(f"SKILL.md 트라이어드: 본문은 {count.group(1)}개라 하고 표는 {len(rows)}줄")

    # (d) 라운드 2·3 프롬프트가 붙이는 "짧은 판"이 문체 규칙 정본에 있어야 한다.
    voice = ROOT / "references" / "voice-rules.md"
    voice_text = voice.read_text(encoding="utf-8") if voice.exists() else ""
    if not re.search(r"^## 짧은 판", voice_text, re.M):
        errors.append("references/voice-rules.md: '## 짧은 판' 제목이 없습니다")

    # (e) 대립극 쌍마다 서로의 정의 파일 "자문단 안에서 제 자리"에 상대의 한국어 이름이 나와야 한다.
    #     이름은 council.figure 와 SKILL.md 대응표의 이름 둘 다 받는다. 절에 없고 파일 다른 곳에만
    #     있으면 통과시키되 참고로 알린다.
    ko_names = {}
    for f in agent_files:
        fig = field(frontmatter(f.read_text(encoding="utf-8")), "figure")
        ko_names.setdefault(f.stem, set()).update({fig} if fig else set())
    for name, s in re.findall(r"([가-힣]+(?: [가-힣]+)*)=([a-z]+(?:-[a-z]+)*)", table_line):
        ko_names.setdefault(s, set()).add(name)
    if duo_line:
        pairs = []
        for pair in duo_line.split("·"):
            two = [x.strip() for x in pair.split("/")]
            if len(two) == 2 and all(x in slugs for x in two):
                pairs.append(tuple(two))
        for a, b in pairs:
            for me, other in ((a, b), (b, a)):
                text = (AGENTS / f"{me}.md").read_text(encoding="utf-8")
                place = section(text, "자문단 안에서 제 자리")
                names = ko_names.get(other, set())
                if place is not None and any(n in place for n in names):
                    continue
                if any(n in text for n in names):
                    where = "절이 없어 파일 전체에서" if place is None else "'자문단 안에서 제 자리' 밖에서만"
                    notes.append(f"대립극 {a} / {b}: {me}.md 가 {where} {'/'.join(sorted(names))} 를 언급")
                    continue
                errors.append(
                    f"대립극 {a} / {b}: {me}.md 의 '자문단 안에서 제 자리'에 상대 이름"
                    f"({'/'.join(sorted(names))})이 없음"
                )

    # (f) tests/cases 의 고정 답(fixture)과 하위 사례 표의 라벨·직답이 그 위원의 세 라벨과
    #     사례 선택지 안에 있어야 한다. 라벨 이름이 바뀌었는데 고정 답이 옛 라벨을 쓰면,
    #     형식 점검을 시험하려던 사례가 의도하지 않은 형식 불일치를 일으킨다.
    #     "의도된 불일치" 표시가 있는 값은 거꾸로, 정말 어긋나는지 본다.
    name_to_slug = {n: s for s, ns in ko_names.items() for n in ns}
    try:
        import resolve_members  # noqa: E402
        name_to_slug.update(resolve_members.NAME_TO_SLUG)
    except Exception:  # noqa: BLE001
        pass
    n_fixture = check_case_fixtures(labels_by_slug, name_to_slug, errors)

    if errors:
        print("FAIL")
        for e in errors:
            print("  -", e)
        for n in notes:
            print("  참고:", n)
        sys.exit(1)

    print(
        f"PASS  {len(agent_files)} agents, names/slugs/sections, 3 labels each, lookup table, "
        "resolve_members, README table, duo pairs (25 covered, names in both files), "
        "selection tilt lists (25 once), triad slugs, README badge = plugin.json version, "
        "voice-rules short version, no em dash, "
        f"case fixtures ({n_fixture} label/answer values vs agent labels and case options)"
    )
    for n in notes:
        print("  참고:", n)
    sys.exit(0)


if __name__ == "__main__":
    main()
