#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

command -v docker >/dev/null 2>&1 || { echo '[ERROR] Docker is unavailable.' >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo '[ERROR] Docker Compose v2 is unavailable.' >&2; exit 1; }

printf '[NuBagz] Stopping app containers safely...\n'
printf 'This command does NOT use -v and does NOT remove the Postgres named volume.\n\n'
docker compose down --remove-orphans
printf '\n[OK] NuBagz stopped. Database volume preserved.\n'
printf 'You can now stop the Codespace safely.\n'
