#!/usr/bin/env bash
#
# AI ROASTING Council installer (Claude Code)
# Installs 25 council agents and the /council skill into your Claude config.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="${HOME}/.claude"
DRY_RUN=false

usage() {
  cat <<'EOF'
AI ROASTING Council installer

Usage:
  ./install.sh                         Install into ~/.claude (default)
  ./install.sh --claude-dir PATH       Install into a custom Claude config dir
  ./install.sh --dry-run               Show what would happen, write nothing
  ./install.sh --help                  Show this help

Files this installer put there before (an earlier council version) are
updated in place. A file with the same name that is not a council file is
kept as <file>.bak before it is replaced (--dry-run lists both).

After installing, restart Claude Code, then run:
  /council Should we enter this market now?
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --claude-dir) CLAUDE_DIR="$2"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
  esac
done

run_cmd() {
  if [[ "${DRY_RUN}" == true ]]; then
    echo "  [dry-run] $*"
  else
    "$@"
  fi
}

# Print the YAML frontmatter (between the first two '---' lines) of a file.
frontmatter() {
  awk 'NR == 1 && $0 != "---" { exit } NR > 1 && $0 == "---" { exit } NR > 1 { print }' "$1"
}

# Is an existing file one that this repository installed (any version)?
#   agent       frontmatter has a 'council:' block
#   skill       frontmatter has 'name: council'
#   voice-rules first line is '# 문체 규칙 (자문단 출력용)'
is_ours() {
  local kind="$1" file="$2"
  case "${kind}" in
    agent) frontmatter "${file}" | grep -q '^council:[[:space:]]*$' ;;
    skill) frontmatter "${file}" | grep -Eq '^name:[[:space:]]*"?council"?[[:space:]]*$' ;;
    voice) [[ "$(head -n 1 "${file}")" == "# 문체 규칙 (자문단 출력용)" ]] ;;
    *) return 1 ;;
  esac
}

# Copy one file. An existing file with different contents is replaced in place
# when it is an earlier council file, and kept as <file>.bak first when it is
# someone else's file (an older .bak is replaced).
BACKED_UP=0
UPDATED=0
install_file() {
  local kind="$1" src="$2" dest="$3"
  if [[ -f "${dest}" ]] && ! cmp -s "${src}" "${dest}"; then
    if is_ours "${kind}" "${dest}"; then
      echo "  update: ${dest} (earlier council version, no backup)"
      UPDATED=$((UPDATED + 1))
    else
      echo "  backup: ${dest} is not a council file, saving it as ${dest}.bak"
      BACKED_UP=$((BACKED_UP + 1))
      run_cmd cp -p "${dest}" "${dest}.bak"
    fi
  fi
  run_cmd install -m 0644 "${src}" "${dest}"
}

# Preflight
if [[ ! -d "${SCRIPT_DIR}/agents" ]]; then
  echo "Error: agents directory not found at ${SCRIPT_DIR}/agents" >&2
  exit 1
fi
if [[ ! -f "${SCRIPT_DIR}/SKILL.md" ]]; then
  echo "Error: SKILL.md not found at ${SCRIPT_DIR}/SKILL.md" >&2
  exit 1
fi

agent_files=("${SCRIPT_DIR}"/agents/*.md)
if [[ ${#agent_files[@]} -eq 0 ]]; then
  echo "Error: no agent files found under ${SCRIPT_DIR}/agents" >&2
  exit 1
fi

AGENTS_DEST="${CLAUDE_DIR}/agents"
SKILL_DEST_DIR="${CLAUDE_DIR}/skills/council"
SKILL_DEST="${SKILL_DEST_DIR}/SKILL.md"

echo "AI ROASTING Council -> ${CLAUDE_DIR}"
run_cmd mkdir -p "${AGENTS_DEST}" "${SKILL_DEST_DIR}"

echo "Installing ${#agent_files[@]} council agents..."
for agent_file in "${agent_files[@]}"; do
  install_file agent "${agent_file}" "${AGENTS_DEST}/$(basename "${agent_file}")"
done

echo "Installing /council skill..."
install_file skill "${SCRIPT_DIR}/SKILL.md" "${SKILL_DEST}"

if [[ -d "${SCRIPT_DIR}/references" ]]; then
  run_cmd mkdir -p "${SKILL_DEST_DIR}/references"
  for ref in "${SCRIPT_DIR}"/references/*.md; do
    if [[ -e "${ref}" ]]; then
      kind=other
      [[ "$(basename "${ref}")" == "voice-rules.md" ]] && kind=voice
      install_file "${kind}" "${ref}" "${SKILL_DEST_DIR}/references/$(basename "${ref}")"
    fi
  done
fi

echo
if [[ "${DRY_RUN}" == true ]]; then
  echo "Dry run. Nothing was written. ${UPDATED} earlier council file(s) would be updated in place,"
  echo "${BACKED_UP} file(s) that are not council files would be backed up as .bak."
else
  echo "Done. Installed ${#agent_files[@]} agents and the /council skill."
  if [[ ${UPDATED} -gt 0 ]]; then
    echo "Updated ${UPDATED} file(s) from an earlier council version in place."
  fi
  if [[ ${BACKED_UP} -gt 0 ]]; then
    echo "Backed up ${BACKED_UP} file(s) that were not council files, as <file>.bak next to the new one."
  fi
fi
echo "Restart Claude Code, then try:  /council Should we ship this quarter?"

# The marketplace plugin and this copy would both register the 25 agents.
PLUGINS_JSON="${CLAUDE_DIR}/plugins/installed_plugins.json"
if [[ -f "${PLUGINS_JSON}" ]] && grep -q '"council@' "${PLUGINS_JSON}"; then
  echo
  echo "Warning: the council plugin is also installed (${PLUGINS_JSON})."
  echo "플러그인과 이 설치본이 함께 있으면 위원이 두 벌 생깁니다. 둘 중 하나만 쓰세요."
fi
