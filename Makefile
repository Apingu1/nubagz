.PHONY: up down logs test-backend
up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f --tail=150

test-backend:
	cd backend && pytest -q
