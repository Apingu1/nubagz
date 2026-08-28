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
    printf '\n[WARN] Working tree has tracked/untracked changes:\n%s\n' "$status"
    printf 'Review these before switching branches or pulling architecture changes.\n'
  else
    printf '\n[OK] Git working tree is clean.\n'
  fi
fi

printf '\n[NuBagz] Creating a verified database checkpoint...\n'
bash scripts/backup_db.sh "$label"

printf '\n[OK] Pre-update checkpoint complete.\n'
printf 'You can now pull/switch to the next forward NuBagz V2 branch.\n'
