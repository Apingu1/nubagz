.PHONY: up down logs test-backend runtime-check backup pre-update verify-backup

up:
	bash run_stack.sh

down:
	bash scripts/safe_stop.sh

logs:
	docker compose logs -f --tail=150

test-backend:
	cd backend && pytest -q

runtime-check:
	bash scripts/runtime_check.sh

backup:
	bash scripts/backup_db.sh MANUAL

pre-update:
	bash scripts/pre_update_check.sh PRE_UPDATE

verify-backup:
	@test -n "$(BACKUP)" || (echo 'Usage: make verify-backup BACKUP=backups/<file>.dump' && exit 2)
	bash scripts/verify_backup.sh "$(BACKUP)"
