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

if [[ ! -f .env ]]; then
  info "No .env found. Creating one from .env.example..."
  [[ -f .env.example ]] || fail ".env.example is missing."
  cp .env.example .env

  if command -v python >/dev/null 2>&1; then
    NEW_SECRET="$(python - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
)"
    python - "$NEW_SECRET" <<'PY'
from pathlib import Path
import sys
secret = sys.argv[1]
path = Path('.env')
lines = path.read_text().splitlines()
out = []
replaced = False
for line in lines:
    if line.startswith('JWT_SECRET='):
        out.append(f'JWT_SECRET={secret}')
        replaced = True
    else:
        out.append(line)
if not replaced:
    out.insert(0, f'JWT_SECRET={secret}')
path.write_text('\n'.join(out) + '\n')
PY
    ok "Created .env with a fresh local JWT secret."
  else
    warn "Python was not available, so .env was copied without generating a new JWT secret."
  fi
else
  ok "Using existing .env file."
fi

info "Building and starting NuBagz..."
docker compose up -d --build --remove-orphans

info "Waiting for NuBagz web root and API health endpoint..."
READY=0
ROOT_CODE="000"
HEALTH_CODE="000"

for _ in $(seq 1 60); do
  ROOT_CODE="$(curl -sS -o /tmp/nubagz-root.html -w '%{http_code}' http://127.0.0.1:8080/ || true)"
  HEALTH_CODE="$(curl -sS -o /tmp/nubagz-health.json -w '%{http_code}' http://127.0.0.1:8080/api/health || true)"

  if [[ "$ROOT_CODE" == "200" && "$HEALTH_CODE" == "200" ]] \
     && grep -q '<title>NuBagz' /tmp/nubagz-root.html \
     && grep -q '"status":"ok"' /tmp/nubagz-health.json; then
    READY=1
    break
  fi

  sleep 2
done

printf '\n'
docker compose ps
printf '\nLocal HTTP diagnostics:\n'
printf '  /            -> HTTP %s\n' "$ROOT_CODE"
printf '  /api/health  -> HTTP %s\n' "$HEALTH_CODE"

if [[ "$READY" -ne 1 ]]; then
  warn "NuBagz did not return the expected production app on port 8080 within the startup window."
  printf '\n--- ROOT RESPONSE (first 30 lines) ---\n'
  sed -n '1,30p' /tmp/nubagz-root.html 2>/dev/null || true
  printf '\n--- HEALTH RESPONSE ---\n'
  cat /tmp/nubagz-health.json 2>/dev/null || true
  printf '\n\n--- API LOGS ---\n'
  docker compose logs --tail=120 api || true
  printf '\n--- WEB LOGS ---\n'
  docker compose logs --tail=120 web || true
  printf '\n--- DATABASE LOGS ---\n'
  docker compose logs --tail=80 db || true
  fail "Startup check failed. Review the diagnostics above."
fi

ok "NuBagz is running and the production root + API health checks both returned HTTP 200."
printf '\nOpen locally: http://localhost:8080\n'

if [[ -n "${CODESPACE_NAME:-}" ]]; then
  DOMAIN="${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-app.github.dev}"
  FORWARDED_URL="https://${CODESPACE_NAME}-8080.${DOMAIN}"
  printf 'Codespaces URL: %s\n' "$FORWARDED_URL"
  printf '\nCodespaces port note:\n'
  printf '  Use port 8080 in the Ports tab (not an old 5173/Vite port).\n'
  printf '  Right-click port 8080 -> Open in Browser.\n'
  printf '  If the forwarded URL shows 404 while the local checks above are 200,\n'
  printf '  the app container is healthy and the issue is the Codespaces port forwarding state.\n'
  printf '  Toggle port 8080 visibility or remove/re-add the forwarded port, then open it again.\n'

  if command -v gh >/dev/null 2>&1; then
    printf '\nCurrent Codespaces forwarded ports (when available):\n'
    gh codespace ports -c "$CODESPACE_NAME" 2>/dev/null || true
  fi
fi

printf '\nUseful commands:\n'
printf '  curl -i http://localhost:8080/           # verify frontend locally\n'
printf '  curl -i http://localhost:8080/api/health # verify API through nginx\n'
printf '  docker compose logs -f                  # follow all logs\n'
printf '  docker compose logs -f api              # backend logs\n'
printf '  docker compose logs -f web              # frontend/nginx logs\n'
printf '  docker compose down                     # stop NuBagz, keep database\n'
printf '  docker compose up -d --build            # rebuild/start manually\n\n'
