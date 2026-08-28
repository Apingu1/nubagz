#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

info()  { printf '\n\033[1;36m[NuBagz]\033[0m %s\n' "$*"; }
ok()    { printf '\033[1;32m[OK]\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m[WARN]\033[0m %s\n' "$*"; }
fail()  { printf '\033[1;31m[ERROR]\033[0m %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || fail "Docker is not installed or not available in this Codespace."
docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 is not available."
[[ -f docker-compose.yml ]] || fail "docker-compose.yml was not found. Run this script from the NuBagz repository."
[[ -f scripts/bootstrap_env.sh ]] || fail "scripts/bootstrap_env.sh is missing."
[[ -f scripts/runtime_check.sh ]] || fail "scripts/runtime_check.sh is missing."

if command -v git >/dev/null 2>&1 && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  BRANCH="$(git branch --show-current 2>/dev/null || true)"
  SHORT_SHA="$(git rev-parse --short HEAD 2>/dev/null || true)"
  info "Source: ${BRANCH:-detached HEAD} @ ${SHORT_SHA:-unknown}"
fi

info "Preparing local runtime configuration..."
# This preserves all existing non-blank local .env values. On a replacement
# Codespace it can also import matching Codespaces/environment secrets without
# printing their values.
bash scripts/bootstrap_env.sh

info "Running Phase 0 preflight checks..."
bash scripts/runtime_check.sh --preflight

info "Building and starting fresh NuBagz app containers..."
printf '[NuBagz] Data safety: this start path NEVER removes Docker named volumes.\n'
printf '[NuBagz] The Postgres volume is preserved while api/web containers are rebuilt.\n'
# --force-recreate prevents an older web/api container from surviving a source
# switch or rebuild. Do not add -v or volume-removal commands to this script.
docker compose up -d --build --force-recreate --remove-orphans

info "Waiting for NuBagz to become ready..."
READY=0
for _ in $(seq 1 60); do
  if curl -fsS --max-time 3 http://127.0.0.1:8080/ >/dev/null 2>&1 \
     && curl -fsS --max-time 3 http://127.0.0.1:8080/api/health 2>/dev/null | grep -q '"status":"ok"'; then
    READY=1
    break
  fi
  sleep 2
done

printf '\n'
docker compose ps

if [[ "$READY" -ne 1 ]]; then
  warn "NuBagz did not become ready on port 8080 within the startup window."
  printf '\n--- API LOGS ---\n'
  docker compose logs --tail=120 api || true
  printf '\n--- WEB LOGS ---\n'
  docker compose logs --tail=120 web || true
  printf '\n--- DATABASE LOGS ---\n'
  docker compose logs --tail=80 db || true
  fail "Startup check failed. Review the logs above."
fi

ok "NuBagz is running."
info "Post-start runtime check..."
bash scripts/runtime_check.sh || warn "NuBagz started, but the runtime checker reported warnings/failures above."

printf '\nOpen: http://localhost:8080\n'

if [[ -n "${CODESPACE_NAME:-}" ]]; then
  DOMAIN="${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-app.github.dev}"
  printf 'Codespaces: https://%s-8080.%s\n' "$CODESPACE_NAME" "$DOMAIN"
  printf 'Use port 8080 in the Codespaces Ports tab.\n'
fi

printf '\nSafe operating commands:\n'
printf '  bash scripts/runtime_check.sh       # configuration + runtime health\n'
printf '  bash scripts/backup_db.sh PRE_UPDATE # verified PostgreSQL backup\n'
printf '  bash scripts/safe_stop.sh           # stop app, KEEP database volume\n'
printf '  docker compose logs -f              # follow all logs\n'
printf '  docker compose logs -f api          # backend logs\n'
printf '  docker compose logs -f web          # frontend logs\n'
printf '\nNever use `docker compose down -v` unless you intentionally want to delete the local database.\n'
printf 'Never use `git clean -fdx` in this repo unless you intentionally want to delete ignored local files such as .env/backups.\n\n'
