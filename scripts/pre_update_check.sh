#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

label="${1:-PRE_UPDATE}"

printf '[NuBagz] Pre-update safety checkpoint\n\n'

bash scripts/runtime_check.sh

if command -v git >/dev/null 2>&1 && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  status="$(git status --short)"
  if [[ -n "$status" ]]; then
    printf '\n[ERROR] Working tree is not clean:\n%s\n' "$status" >&2
    printf '\nCommit, stash, or deliberately remove these changes before switching/pulling a NuBagz V2 branch.\n' >&2
    printf 'The safety checkpoint has stopped; no source switch should be performed yet.\n' >&2
    exit 1
  fi
  printf '\n[OK] Git working tree is clean.\n'
fi

printf '\n[NuBagz] Creating a verified database checkpoint...\n'
bash scripts/backup_db.sh "$label"

printf '\n[OK] Pre-update checkpoint complete.\n'
printf 'The runtime passed, Git is clean, and a verified database backup now exists.\n'
printf 'You can safely perform the planned forward branch switch/pull.\n'
