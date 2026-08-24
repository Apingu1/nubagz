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

if command -v git >/dev/null 2>&1 && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  BRANCH="$(git branch --show-current 2>/dev/null || true)"
  SHORT_SHA="$(git rev-parse --short HEAD 2>/dev/null || true)"
  info "Source: ${BRANCH:-detached HEAD} @ ${SHORT_SHA:-unknown}"
fi

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

# The NuBagz Privy App ID and identity-token verification key are public
# configuration. Keep an existing non-blank local value, but automatically copy
# the repo's public defaults into older Codespace .env files that pre-date the
# social-login setup. Private secrets are intentionally never backfilled here.
if [[ -f .env.example ]] && command -v python >/dev/null 2>&1; then
  BACKFILLED_PRIVY="$(python - <<'PY'
from pathlib import Path

keys = ("VITE_PRIVY_APP_ID", "PRIVY_APP_ID", "PRIVY_VERIFICATION_KEY")
env_path = Path('.env')
example_path = Path('.env.example')

def entries(lines):
    result = {}
    for index, line in enumerate(lines):
        if '=' not in line or line.lstrip().startswith('#'):
            continue
        key, value = line.split('=', 1)
        result[key.strip()] = (index, value)
    return result

env_lines = env_path.read_text().splitlines()
example_lines = example_path.read_text().splitlines()
env_entries = entries(env_lines)
example_entries = entries(example_lines)
updated = []

for key in keys:
    source = example_entries.get(key)
    if not source:
        continue
    _, source_value = source
    if not source_value.strip().strip("'\""):
        continue
    current = env_entries.get(key)
    if current and current[1].strip().strip("'\""):
        continue
    replacement = f"{key}={source_value}"
    if current:
        env_lines[current[0]] = replacement
    else:
        env_lines.append(replacement)
    env_entries = entries(env_lines)
    updated.append(key)

if updated:
    env_path.write_text('\n'.join(env_lines) + '\n')
print(','.join(updated))
PY
)"
  if [[ -n "$BACKFILLED_PRIVY" ]]; then
    ok "Added NuBagz public Privy configuration to .env: $BACKFILLED_PRIVY"
  fi
fi

get_env_value() {
  local key="$1"
  sed -n "s/^${key}=//p" .env | tail -n 1
}

VITE_PRIVY_APP_ID_VALUE="$(get_env_value VITE_PRIVY_APP_ID)"
PRIVY_APP_ID_VALUE="$(get_env_value PRIVY_APP_ID)"
PRIVY_VERIFICATION_KEY_VALUE="$(get_env_value PRIVY_VERIFICATION_KEY)"

if [[ -z "$VITE_PRIVY_APP_ID_VALUE" ]]; then
  warn "VITE_PRIVY_APP_ID is blank. X/Google login and Connected Accounts will be hidden until Privy is configured in .env."
elif [[ -z "$PRIVY_APP_ID_VALUE" || -z "$PRIVY_VERIFICATION_KEY_VALUE" ]]; then
  warn "Privy frontend is configured, but backend identity verification is incomplete. Set PRIVY_APP_ID and PRIVY_VERIFICATION_KEY in .env before testing social login."
else
  ok "Privy social-login environment is configured."
fi

info "Building and starting fresh NuBagz app containers..."
# --force-recreate prevents an older web/api container from surviving a source
# switch or rebuild. The named Postgres volume remains intact, so application
# data is preserved while the app containers are refreshed.
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
printf '\nOpen: http://localhost:8080\n'

if [[ -n "${CODESPACE_NAME:-}" ]]; then
  DOMAIN="${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-app.github.dev}"
  printf 'Codespaces: https://%s-8080.%s\n' "$CODESPACE_NAME" "$DOMAIN"
  printf 'Use port 8080 in the Codespaces Ports tab.\n'
fi

printf '\nUseful commands:\n'
printf '  docker compose logs -f          # follow all logs\n'
printf '  docker compose logs -f api      # backend logs\n'
printf '  docker compose logs -f web      # frontend logs\n'
printf '  docker compose down             # stop NuBagz, keep database\n'
printf '  docker compose up -d --build --force-recreate  # rebuild/start manually\n\n'
