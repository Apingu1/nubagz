# NuBagz Runtime & Data Safety Baseline

This document defines the Phase 0 development baseline used before the NuBagz V2 architecture work.

## Core guarantees

- `.env` is local and ignored by Git. Branch switches do not replace a working `.env`.
- `run_stack.sh` preserves the named PostgreSQL Docker volume. It never uses `docker compose down -v`.
- database backups are stored under ignored `backups/` and are never committed by normal Git operations.
- pre-update checkpoints require a clean Git working tree and a verified PostgreSQL backup.
- private keys/API keys must never be committed to this repository.

## Existing Codespace

A normal forward branch switch in the same `/workspaces/nubagz` Codespace keeps the existing `.env` and Docker named database volume.

Before a significant source update or branch switch run:

```bash
bash scripts/pre_update_check.sh PRE_UPDATE
```

That command:

1. checks the current runtime/configuration;
2. refuses to continue if Git has local tracked/untracked changes;
3. creates a PostgreSQL custom-format backup;
4. validates the archive with `pg_restore --list`;
5. writes a SHA-256 checksum and metadata sidecar.

Then perform the planned forward Git switch/pull.

## Starting NuBagz

Use:

```bash
bash run_stack.sh
```

`run_stack.sh` first executes the environment bootstrap and runtime preflight, then rebuilds/recreates application containers while preserving the PostgreSQL named volume.

## Runtime check

```bash
bash scripts/runtime_check.sh
```

For configuration-only checks before containers are started:

```bash
bash scripts/runtime_check.sh --preflight
```

The checker reports whether sensitive values are configured but does not print secret values.

## Environment portability

The repository contains only `.env.example`. The real `.env` remains local.

```bash
bash scripts/bootstrap_env.sh
```

Behaviour:

- creates `.env` when missing;
- forward-fills newly introduced configuration keys from `.env.example`;
- preserves existing non-blank local values by default;
- imports matching process/Codespaces environment variables when the local key is blank/missing;
- never prints API keys/private-key values.

For a replacement Codespace, configure the required values as Codespaces/repository secrets using the same variable names, then run the bootstrap script. Typical sensitive variables include:

- `JWT_PRIVATE_KEY`
- `JWT_PUBLIC_KEY`
- `ZEROX_API_KEY`
- `LIFI_API_KEY`
- any private provider API keys introduced later

Public/runtime variables such as `JWT_ALGORITHM`, `JWT_KEY_ID`, `PRIVY_APP_ID`, `VITE_PRIVY_APP_ID`, `LIFI_INTEGRATOR`, `NUBAGZ_SWAP_FEE_BPS`, and the public NuBagz fee-recipient address can also be provided as environment variables.

The bootstrap helper deliberately does **not** upload the existing `.env` anywhere. Secret-manager configuration remains an explicit operator action.

## Database backups

Create a labelled backup:

```bash
bash scripts/backup_db.sh PRE_PHASE_1
```

Each checkpoint produces three ignored local files:

```text
backups/<name>.dump
backups/<name>.dump.sha256
backups/<name>.txt
```

Re-verify any checkpoint without restoring it:

```bash
bash scripts/verify_backup.sh backups/<name>.dump
```

Verification checks the checksum (when present) and confirms the archive can be read by PostgreSQL restore tooling. It does not modify a database.

Backups stored only in a Codespace disappear if the Codespace itself is deleted. Important checkpoints should therefore also be exported to an approved secure location before deleting/rebuilding a development environment.

## Safe stop

```bash
bash scripts/safe_stop.sh
```

This stops containers without deleting the named PostgreSQL volume.

## Commands to avoid during ordinary development

Do not use:

```bash
docker compose down -v
git clean -fdx
```

`docker compose down -v` removes named volumes, including the local PostgreSQL dataset. `git clean -fdx` can remove ignored local files such as `.env` and `backups/`.

Only use either command when deliberately resetting the development environment and after making the required backups.

## Forward-only V2 branch strategy

The V2 development flow is cumulative:

```text
working swap baseline
  -> Phase 0 runtime/data baseline
  -> develop/nubagz-v2
  -> feature/domain-navigation-v2
  -> feature/security-user-trust-v2
  -> feature/challenge-submission-engine
  -> ...
```

Each accepted feature branch should start from the latest accepted V2 integration baseline. Database schema changes must be additive/migrated forward and preceded by a verified database checkpoint.

Phase 0 does not attempt to rewrite the current domain schema. The formal domain cleanup and migration work begins in Phase 1.
