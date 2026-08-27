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
import re
import sys
from pathlib import Path

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


def main():
    errors = []
    agent_files = sorted(AGENTS.glob("*.md"))
    slugs = {f.stem for f in agent_files}

    if len(agent_files) != 25:
        errors.append(f"expected 25 agents, found {len(agent_files)}")

    skill_text = SKILL.read_text(encoding="utf-8") if SKILL.exists() else ""

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
    for doc in sorted(ROOT.glob("*.md")) + sorted((ROOT / "docs").glob("*.md")) + sorted(
        (ROOT / "references").glob("*.md")
    ):
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

    if errors:
        print("FAIL")
        for e in errors:
            print("  -", e)
        sys.exit(1)

    print(
        f"PASS  {len(agent_files)} agents, names/slugs/sections consistent, "
        "lookup table, resolve_members, README table, duo pairs in sync, no em dash"
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
