#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

label="${1:-MANUAL}"
label="$(printf '%s' "$label" | tr '[:lower:] ' '[:upper:]_' | tr -cd 'A-Z0-9_.-')"
[[ -n "$label" ]] || label="MANUAL"

command -v docker >/dev/null 2>&1 || { echo '[ERROR] Docker is unavailable.' >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo '[ERROR] Docker Compose v2 is unavailable.' >&2; exit 1; }

if ! docker compose ps --status running --services 2>/dev/null | grep -qx 'db'; then
  echo '[ERROR] NuBagz Postgres is not running. Start the stack before taking a database backup.' >&2
  exit 1
fi

mkdir -p backups
chmod 700 backups 2>/dev/null || true

stamp="$(date -u +'%Y%m%dT%H%M%SZ')"
branch="$(git branch --show-current 2>/dev/null || echo unknown)"
sha="$(git rev-parse HEAD 2>/dev/null || echo unknown)"
short_sha="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
safe_branch="$(printf '%s' "$branch" | tr '/ ' '__' | tr -cd 'A-Za-z0-9_.-')"
base="backups/nubagz_${stamp}_${label}_${safe_branch}_${short_sha}"
dump_file="${base}.dump"
meta_file="${base}.txt"
tmp_file="${dump_file}.partial"

cleanup(){ rm -f "$tmp_file"; }
trap cleanup EXIT

printf '[NuBagz] Creating PostgreSQL backup...\n'
docker compose exec -T db pg_dump -U nubagz -d nubagz -Fc > "$tmp_file"

if [[ ! -s "$tmp_file" ]]; then
  echo '[ERROR] pg_dump produced an empty file.' >&2
  exit 1
fi

# Validate the custom-format archive through the same Postgres image before
# declaring it usable.
if ! docker compose exec -T db pg_restore --list - < "$tmp_file" >/dev/null; then
  echo '[ERROR] pg_restore could not read the generated archive. Backup rejected.' >&2
  exit 1
fi

mv "$tmp_file" "$dump_file"
chmod 600 "$dump_file" 2>/dev/null || true
size_bytes="$(wc -c < "$dump_file" | tr -d ' ')"

cat > "$meta_file" <<EOF
NuBagz PostgreSQL backup
created_utc=$stamp
label=$label
branch=$branch
commit=$sha
database=nubagz
format=PostgreSQL custom archive
size_bytes=$size_bytes
restore_note=Use an explicit reviewed restore procedure; never overwrite a live dataset casually.
EOF
chmod 600 "$meta_file" 2>/dev/null || true

printf '[OK] Verified database backup created.\n'
printf '  %s\n' "$dump_file"
printf '  %s\n' "$meta_file"
printf '  Size: %s bytes\n' "$size_bytes"
printf '\nThis helper never modifies or removes the running database volume.\n'
