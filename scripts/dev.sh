#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

bash scripts/bootstrap_env.sh
bash scripts/runtime_check.sh --preflight

printf '[NuBagz] Starting attached development stack. Named database volumes are preserved.\n'
docker compose up --build
