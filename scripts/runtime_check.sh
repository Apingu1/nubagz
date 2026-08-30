#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

MODE="${1:-full}"
if [[ "$MODE" != "full" && "$MODE" != "--preflight" ]]; then
  printf '[ERROR] Usage: bash scripts/runtime_check.sh [--preflight]\n' >&2
  exit 2
fi

failures=0
warnings=0
ok(){ printf '\033[1;32m[OK]\033[0m %s\n' "$*"; }
warn(){ warnings=$((warnings+1)); printf '\033[1;33m[WARN]\033[0m %s\n' "$*"; }
fail(){ failures=$((failures+1)); printf '\033[1;31m[FAIL]\033[0m %s\n' "$*"; }

printf '\n[NuBagz] Runtime baseline check\n\n'

command -v docker >/dev/null 2>&1 && ok 'Docker available.' || fail 'Docker is unavailable.'
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  ok 'Docker Compose v2 available.'
else
  fail 'Docker Compose v2 is unavailable.'
fi

[[ -f docker-compose.yml ]] && ok 'docker-compose.yml present.' || fail 'docker-compose.yml missing.'
[[ -f .env.example ]] && ok '.env.example present.' || fail '.env.example missing.'
[[ -f .env ]] && ok '.env present.' || fail '.env missing. Run: bash scripts/bootstrap_env.sh'

if command -v git >/dev/null 2>&1 && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  branch="$(git branch --show-current 2>/dev/null || true)"
  sha="$(git rev-parse --short HEAD 2>/dev/null || true)"
  printf 'Source: %s @ %s\n' "${branch:-detached}" "${sha:-unknown}"
  if git ls-files --error-unmatch .env >/dev/null 2>&1; then
    fail '.env is tracked by Git. Secrets must remain local.'
  else
    ok '.env is not tracked by Git.'
  fi
fi

if [[ ! -f .env ]]; then
  printf '\nResult: FAILED (%d failure(s), %d warning(s))\n' "$failures" "$warnings"
  exit 1
fi

python3 - <<'PY'
from pathlib import Path

path = Path('.env')
items = {}
for line in path.read_text().splitlines():
    stripped = line.strip()
    if not stripped or stripped.startswith('#') or '=' not in line:
        continue
    key, value = line.split('=', 1)
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    items[key.strip()] = value

secret = {
    'JWT_SECRET','JWT_PRIVATE_KEY','JWT_PUBLIC_KEY','PRIVY_VERIFICATION_KEY',
    'ZEROX_API_KEY','LIFI_API_KEY','SWAP_PROVIDER_API_KEY','GAS_SPONSOR_PROVIDER_API_KEY'
}
public = ['JWT_ALGORITHM','JWT_KEY_ID','JWT_AUDIENCE','VITE_PRIVY_APP_ID','PRIVY_APP_ID','EVM_RPC_ROBINHOOD','LIFI_INTEGRATOR','NUBAGZ_SWAP_FEE_BPS','NUBAGZ_SWAP_FEE_RECIPIENT']
for key in sorted(secret):
    print(f'ENV|{key}|{"CONFIGURED" if items.get(key) else "NOT SET"}|SECRET')
for key in public:
    value = items.get(key, '')
    if key in {'NUBAGZ_SWAP_FEE_RECIPIENT','EVM_RPC_ROBINHOOD'}:
        shown = 'CONFIGURED' if value else 'NOT SET'
    else:
        shown = value or 'NOT SET'
    print(f'ENV|{key}|{shown}|PUBLIC')
PY

get_env(){
  local key="$1"
  sed -n "s/^${key}=//p" .env | tail -n 1 | sed -e "s/^['\"]//" -e "s/['\"]$//"
}

JWT_ALGORITHM_VALUE="$(get_env JWT_ALGORITHM)"
JWT_AUDIENCE_VALUE="$(get_env JWT_AUDIENCE)"
JWT_PRIVATE_KEY_VALUE="$(get_env JWT_PRIVATE_KEY)"
JWT_PUBLIC_KEY_VALUE="$(get_env JWT_PUBLIC_KEY)"
VITE_PRIVY_APP_ID_VALUE="$(get_env VITE_PRIVY_APP_ID)"
PRIVY_APP_ID_VALUE="$(get_env PRIVY_APP_ID)"
PRIVY_VERIFICATION_KEY_VALUE="$(get_env PRIVY_VERIFICATION_KEY)"
ZEROX_API_KEY_VALUE="$(get_env ZEROX_API_KEY)"
LIFI_INTEGRATOR_VALUE="$(get_env LIFI_INTEGRATOR)"
NUBAGZ_SWAP_FEE_BPS_VALUE="$(get_env NUBAGZ_SWAP_FEE_BPS)"
NUBAGZ_SWAP_FEE_RECIPIENT_VALUE="$(get_env NUBAGZ_SWAP_FEE_RECIPIENT)"
EVM_RPC_ROBINHOOD_VALUE="$(get_env EVM_RPC_ROBINHOOD)"

[[ -n "$JWT_AUDIENCE_VALUE" ]] && ok "JWT audience configured as ${JWT_AUDIENCE_VALUE}." || fail 'JWT_AUDIENCE is blank.'

if [[ "${JWT_ALGORITHM_VALUE^^}" == "RS256" ]]; then
  [[ -n "$JWT_PRIVATE_KEY_VALUE" ]] && ok 'RS256 private signing key configured.' || fail 'JWT_ALGORITHM=RS256 but JWT_PRIVATE_KEY is blank.'
  [[ -n "$JWT_PUBLIC_KEY_VALUE" ]] && ok 'RS256 public verification key configured.' || fail 'JWT_ALGORITHM=RS256 but JWT_PUBLIC_KEY is blank.'
else
  warn "JWT_ALGORITHM is ${JWT_ALGORITHM_VALUE:-unset}; RS256 is required by production NuBagz."
fi

[[ -n "$VITE_PRIVY_APP_ID_VALUE" && -n "$PRIVY_APP_ID_VALUE" ]] && ok 'Privy frontend/backend App IDs configured.' || warn 'Privy App ID configuration is incomplete.'
[[ -n "$PRIVY_VERIFICATION_KEY_VALUE" ]] && ok 'Privy identity verification key configured.' || warn 'PRIVY_VERIFICATION_KEY is blank.'
[[ -n "$EVM_RPC_ROBINHOOD_VALUE" ]] && ok 'Robinhood Chain RPC configured.' || fail 'EVM_RPC_ROBINHOOD is blank.'

if [[ -n "$ZEROX_API_KEY_VALUE" ]]; then
  if [[ "$NUBAGZ_SWAP_FEE_RECIPIENT_VALUE" =~ ^0x[0-9a-fA-F]{40}$ ]]; then
    ok '0x is configured with a valid-looking NuBagz EVM fee recipient.'
  else
    fail 'ZEROX_API_KEY is configured but NUBAGZ_SWAP_FEE_RECIPIENT is missing/invalid.'
  fi
else
  warn 'ZEROX_API_KEY is blank; 0x routes will be unavailable.'
fi

[[ -n "$LIFI_INTEGRATOR_VALUE" ]] && ok 'LI.FI integrator configured.' || warn 'LIFI_INTEGRATOR is blank; LI.FI routes will be unavailable.'

if [[ "$NUBAGZ_SWAP_FEE_BPS_VALUE" =~ ^[0-9]+$ ]] && (( NUBAGZ_SWAP_FEE_BPS_VALUE >= 0 && NUBAGZ_SWAP_FEE_BPS_VALUE <= 1000 )); then
  ok "NuBagz swap fee configured at ${NUBAGZ_SWAP_FEE_BPS_VALUE} bps."
else
  fail 'NUBAGZ_SWAP_FEE_BPS must be an integer between 0 and 1000.'
fi

if command -v docker >/dev/null 2>&1 && docker compose config >/dev/null 2>&1; then
  ok 'Docker Compose configuration renders successfully.'
else
  fail 'Docker Compose configuration could not be rendered.'
fi

if [[ "$MODE" == "full" ]]; then
  if docker compose ps --status running --services 2>/dev/null | grep -qx 'db'; then
    ok 'Postgres service is running.'
  else
    warn 'Postgres service is not currently running.'
  fi
  if curl -fsS --max-time 3 http://127.0.0.1:8080/api/health 2>/dev/null | grep -q '"status":"ok"'; then
    ok 'NuBagz API health endpoint is ready.'
  else
    warn 'NuBagz API is not currently ready on localhost:8080.'
  fi
fi

printf '\nResult: %s (%d failure(s), %d warning(s))\n' "$([[ "$failures" -eq 0 ]] && echo PASSED || echo FAILED)" "$failures" "$warnings"
[[ "$failures" -eq 0 ]]
