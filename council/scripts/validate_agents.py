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
    "## 정체",
    "## 핵심 원칙",
    "## 결정 규칙",
    "## 환각 방지 규칙",
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

    if errors:
        print("FAIL")
        for e in errors:
            print("  -", e)
        sys.exit(1)

    print(
        f"PASS  {len(agent_files)} agents, names/slugs/sections consistent, "
        "lookup table and resolve_members in sync, no em dash"
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
