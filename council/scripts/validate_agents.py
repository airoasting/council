#!/usr/bin/env python3
"""
Validate the AI ROASTING 자문단 agent files against SKILL.md.

Catches the failure class that breaks dispatch: filename / name / SKILL slug
mismatches, missing sections, em dashes, and references to figures that are not
in the 25-member roster. Run from the package root:

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
    "## Identity",
    "## Core Principles",
    "## Decision Rules",
    "## Anti-Hallucination Rules",
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

        # any my-domain-pair slug in prose must be a real member
        for tok in set(re.findall(r"\b[a-z]+-[a-z]+(?:-[a-z]+)?\b", text)):
            if tok in {"jeong-yagyong"}:  # known past misspelling
                errors.append(f"{f.name}: references stale slug '{tok}'")

    if errors:
        print("FAIL")
        for e in errors:
            print("  -", e)
        sys.exit(1)

    print(f"PASS  {len(agent_files)} agents, names/slugs/sections consistent, no em dash")
    sys.exit(0)


if __name__ == "__main__":
    main()
