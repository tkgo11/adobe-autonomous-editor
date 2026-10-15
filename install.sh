#!/usr/bin/env bash
set -euo pipefail

SCOPE="user"
PROJECT_ROOT="$(pwd)"
FORCE=0
SKIP_VALIDATION=0
REPO="https://github.com/tkgo11/adobe-autonomous-editor.git"
SKILL_NAME="adobe-autonomous-editor"

usage() {
  cat <<'EOF'
Usage: ./install.sh [--user | --project [PATH]] [--force] [--skip-validation]

Installs this Agent Skill into a standard .agents/skills directory.
Git is optional; curl/wget + tar provide the archive fallback.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --user) SCOPE="user"; shift ;;
    --project)
      SCOPE="project"
      if [[ $# -gt 1 && "${2:-}" != --* ]]; then PROJECT_ROOT="$2"; shift 2; else shift; fi
      ;;
    --force) FORCE=1; shift ;;
    --skip-validation) SKIP_VALIDATION=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

archive_install() {
  local destination="$1" temp archive source
  temp=$(mktemp -d)
  archive="$temp/skill.tar.gz"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "https://github.com/tkgo11/adobe-autonomous-editor/archive/refs/heads/main.tar.gz" -o "$archive"
  elif command -v wget >/dev/null 2>&1; then
    wget -q "https://github.com/tkgo11/adobe-autonomous-editor/archive/refs/heads/main.tar.gz" -O "$archive"
  else
    echo "Git or a system HTTP client (curl/wget) is required to install the skill." >&2
    return 1
  fi
  if tar -tzf "$archive" | grep -Eq '(^/|(^|/)\.\.(/|$))'; then
    echo "Refusing unsafe skill archive paths." >&2
    return 1
  fi
  tar -xzf "$archive" -C "$temp"
  source="$temp/adobe-autonomous-editor-main"
  [[ -f "$source/SKILL.md" ]] || { echo "Downloaded skill archive is incomplete." >&2; return 1; }
  mv "$source" "$destination"
  : > "$destination/.installed-from-archive"
  rm -rf "$temp"
}

if [[ "$SCOPE" == "user" ]]; then
  SKILLS_ROOT="${HOME}/.agents/skills"
else
  PROJECT_ROOT="$(cd "$PROJECT_ROOT" && pwd)"
  SKILLS_ROOT="${PROJECT_ROOT}/.agents/skills"
fi

DEST="${SKILLS_ROOT}/${SKILL_NAME}"
mkdir -p "$SKILLS_ROOT"

if [[ -e "$DEST" ]]; then
  if [[ -d "$DEST/.git" ]] && command -v git >/dev/null 2>&1; then
    echo "Updating existing skill at $DEST"
    git -C "$DEST" pull --ff-only
  elif [[ "$FORCE" -eq 1 || -f "$DEST/.installed-from-archive" ]]; then
    echo "Replacing existing non-git directory at $DEST"
    rm -rf "$DEST"
    if command -v git >/dev/null 2>&1; then git clone --depth 1 "$REPO" "$DEST"; else archive_install "$DEST"; fi
  else
    echo "Destination exists and is not a git checkout: $DEST" >&2
    echo "Rerun with --force to replace it." >&2
    exit 1
  fi
else
  echo "Installing $SKILL_NAME to $DEST"
  if command -v git >/dev/null 2>&1; then git clone --depth 1 "$REPO" "$DEST"; else archive_install "$DEST"; fi
fi

[[ -f "$DEST/SKILL.md" ]] || { echo "SKILL.md is missing after install." >&2; exit 1; }
[[ -f "$DEST/agents/openai.yaml" ]] || { echo "agents/openai.yaml is missing after install." >&2; exit 1; }
grep -Eq '^name:[[:space:]]*adobe-autonomous-editor[[:space:]]*$' "$DEST/SKILL.md" || {
  echo "SKILL.md frontmatter name is invalid." >&2; exit 1;
}

if [[ "$SKIP_VALIDATION" -eq 0 ]] && command -v python3 >/dev/null 2>&1; then
  echo "Running package self-test..."
  python3 "$DEST/tests/selftest.py"
fi

cat <<EOF

Installed successfully: $DEST
Restart your agent (or start a new session) so skill discovery refreshes.
Invoke explicitly with: \$adobe-autonomous-editor

macOS supports Crafting Apps plus Premiere/After Effects API and Accessibility fallbacks.
Linux supports the Crafting Apps/media pipeline; Adobe desktop applications are not available on Linux.
EOF
