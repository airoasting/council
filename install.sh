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

# Preflight
if [[ ! -d "${SCRIPT_DIR}/agents" ]]; then
  echo "Error: agents directory not found at ${SCRIPT_DIR}/agents" >&2
  exit 1
fi
if [[ ! -f "${SCRIPT_DIR}/SKILL.md" ]]; then
  echo "Error: SKILL.md not found at ${SCRIPT_DIR}/SKILL.md" >&2
  exit 1
fi

# voice-rules.md is a style-rules file, not an agent persona; install it into
# the skill dir separately (below), never into ~/.claude/agents.
agent_files=()
for f in "${SCRIPT_DIR}"/agents/*.md; do
  [[ "$(basename "${f}")" == "voice-rules.md" ]] && continue
  agent_files+=("${f}")
done
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
  run_cmd install -m 0644 "${agent_file}" "${AGENTS_DEST}/"
done

echo "Installing /council skill..."
run_cmd install -m 0644 "${SCRIPT_DIR}/SKILL.md" "${SKILL_DEST}"

if [[ -f "${SCRIPT_DIR}/agents/voice-rules.md" ]]; then
  echo "Installing voice rules..."
  run_cmd install -m 0644 "${SCRIPT_DIR}/agents/voice-rules.md" "${SKILL_DEST_DIR}/voice-rules.md"
fi

echo
echo "Done. Installed ${#agent_files[@]} agents and the /council skill."
echo "Restart Claude Code, then try:  /council Should we ship this quarter?"
