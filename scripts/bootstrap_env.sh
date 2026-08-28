#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

MODE="preserve"
if [[ "${1:-}" == "--refresh-from-env" ]]; then
  MODE="refresh"
elif [[ -n "${1:-}" ]]; then
  printf '[ERROR] Unknown option: %s\n' "$1" >&2
  printf 'Usage: bash scripts/bootstrap_env.sh [--refresh-from-env]\n' >&2
  exit 2
fi

[[ -f .env.example ]] || { echo '[ERROR] .env.example is missing.' >&2; exit 1; }

if command -v git >/dev/null 2>&1 && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  if git ls-files --error-unmatch .env >/dev/null 2>&1; then
    echo '[ERROR] .env is tracked by Git. Refusing to continue with secrets in a tracked file.' >&2
    exit 1
  fi
fi

python3 - "$MODE" <<'PY'
from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path

mode = sys.argv[1]
env_path = Path('.env')
example_path = Path('.env.example')

SECRET_KEYS = {
    'JWT_SECRET',
    'JWT_PRIVATE_KEY',
    'JWT_PUBLIC_KEY',
    'PRIVY_VERIFICATION_KEY',
    'ZEROX_API_KEY',
    'LIFI_API_KEY',
    'SWAP_PROVIDER_API_KEY',
    'GAS_SPONSOR_PROVIDER_API_KEY',
}

PORTABLE_KEYS = [
    'JWT_SECRET',
    'JWT_ALGORITHM',
    'JWT_KEY_ID',
    'JWT_PRIVATE_KEY',
    'JWT_PUBLIC_KEY',
    'VITE_PRIVY_APP_ID',
    'VITE_PRIVY_CLIENT_ID',
    'PRIVY_APP_ID',
    'PRIVY_VERIFICATION_KEY',
    'EVM_RPC_ROBINHOOD',
    'EVM_RPC_AVALANCHE',
    'EVM_RPC_ETHEREUM',
    'EVM_RPC_BASE',
    'EVM_RPC_ARBITRUM',
    'EVM_RPC_POLYGON',
    'ZEROX_API_KEY',
    'LIFI_API_KEY',
    'LIFI_INTEGRATOR',
    'NUBAGZ_SWAP_FEE_BPS',
    'NUBAGZ_SWAP_FEE_RECIPIENT',
    'SWAP_PROVIDER_BASE_URL',
    'SWAP_PROVIDER_API_KEY',
    'GAS_SPONSOR_PROVIDER_BASE_URL',
    'GAS_SPONSOR_PROVIDER_API_KEY',
]


def split_entry(line: str):
    stripped = line.strip()
    if not stripped or stripped.startswith('#') or '=' not in line:
        return None
    key, value = line.split('=', 1)
    key = key.strip()
    return key, value


def clean_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'\'', '"'}:
        return value[1:-1]
    return value


def encode_value(value: str) -> str:
    # Codespaces secrets can contain real PEM newlines. NuBagz's runtime already
    # converts literal \n back to PEM newlines when loading JWT keys.
    value = value.replace('\r\n', '\n').replace('\r', '\n').replace('\n', r'\n')
    if any(ch.isspace() for ch in value) or '#' in value:
        return "'" + value.replace("'", "'\"'\"'") + "'"
    return value


example_lines = example_path.read_text().splitlines()
if env_path.exists():
    env_lines = env_path.read_text().splitlines()
    created = False
else:
    env_lines = list(example_lines)
    created = True


def index(lines: list[str]):
    result = {}
    for i, line in enumerate(lines):
        parsed = split_entry(line)
        if parsed:
            result[parsed[0]] = (i, parsed[1])
    return result


example_index = index(example_lines)
env_index = index(env_lines)
changed = []

# Forward-fill keys newly introduced in later branches without touching existing
# non-blank local values.
for key, (source_i, source_value) in example_index.items():
    if key not in env_index:
        env_lines.append(f'{key}={source_value}')
        env_index = index(env_lines)
        changed.append(f'{key}:schema')

# Import values exposed to the Codespace/process environment. By default this
# only fills blank/missing values, so branch switching cannot overwrite a known
# working .env. --refresh-from-env is explicit opt-in replacement.
for key in PORTABLE_KEYS:
    incoming = os.environ.get(key)
    if incoming is None or incoming == '':
        continue
    current = env_index.get(key)
    current_value = clean_value(current[1]) if current else ''
    if mode != 'refresh' and current_value:
        continue
    encoded = encode_value(incoming)
    if current:
        env_lines[current[0]] = f'{key}={encoded}'
    else:
        env_lines.append(f'{key}={encoded}')
    env_index = index(env_lines)
    changed.append(f'{key}:environment')

# A fresh local HS256 setup should never inherit the example placeholder.
current_secret = env_index.get('JWT_SECRET')
secret_value = clean_value(current_secret[1]) if current_secret else ''
if not secret_value or secret_value == 'replace-with-a-long-random-production-secret':
    generated = secrets.token_urlsafe(48)
    if current_secret:
        env_lines[current_secret[0]] = f'JWT_SECRET={generated}'
    else:
        env_lines.insert(0, f'JWT_SECRET={generated}')
    env_index = index(env_lines)
    changed.append('JWT_SECRET:generated')

env_path.write_text('\n'.join(env_lines) + '\n')
try:
    env_path.chmod(0o600)
except OSError:
    pass

print('CREATED' if created else 'EXISTING')
for item in changed:
    key, source = item.split(':', 1)
    sensitivity = 'SECRET' if key in SECRET_KEYS else 'CONFIG'
    print(f'{key}|{source}|{sensitivity}')
PY

printf '\n[NuBagz] Environment bootstrap complete.\n'
printf '  .env is local/ignored and was not printed.\n'
printf '  Existing non-blank values were %s.\n' "$([[ "$MODE" == "refresh" ]] && echo 'eligible for explicit refresh from process/Codespaces secrets' || echo 'preserved')"
printf '\nFor a replacement Codespace, expose the same variable names as Codespaces secrets, then run:\n'
printf '  bash scripts/bootstrap_env.sh\n'
