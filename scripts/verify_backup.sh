#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

backup="${1:-}"
if [[ -z "$backup" ]]; then
  echo '[ERROR] Usage: bash scripts/verify_backup.sh backups/<file>.dump' >&2
  exit 2
fi
[[ -f "$backup" ]] || { printf '[ERROR] Backup not found: %s\n' "$backup" >&2; exit 1; }
[[ -s "$backup" ]] || { printf '[ERROR] Backup is empty: %s\n' "$backup" >&2; exit 1; }
command -v docker >/dev/null 2>&1 || { echo '[ERROR] Docker is unavailable.' >&2; exit 1; }
command -v sha256sum >/dev/null 2>&1 || { echo '[ERROR] sha256sum is unavailable.' >&2; exit 1; }

checksum_file="${backup}.sha256"
if [[ -f "$checksum_file" ]]; then
  printf '[NuBagz] Verifying SHA-256 checksum...\n'
  sha256sum --check "$checksum_file"
else
  printf '[WARN] No checksum sidecar found for %s. Archive structure will still be tested.\n' "$backup"
fi

printf '[NuBagz] Verifying PostgreSQL custom archive structure...\n'
# pg_restore consumes the archive from stdin when the archive filename is
# omitted. Do not pass '-' because pg_restore treats it as a literal filename.
if docker compose ps --status running --services 2>/dev/null | grep -qx 'db'; then
  docker compose exec -T db pg_restore --list < "$backup" >/dev/null
else
  # Verification does not need database access. Use the same Postgres major
  # version in an isolated disposable container when the NuBagz DB is stopped.
  docker run --rm -i postgres:16-alpine pg_restore --list < "$backup" >/dev/null
fi

printf '[OK] Backup checksum/archive verification passed: %s\n' "$backup"
printf 'No restore was performed and no database was modified.\n'
