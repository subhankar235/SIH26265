up:
	docker compose up --build
seed:
	docker compose exec backend python -m scripts.seed
migrate:
	docker compose exec backend alembic upgrade head
test:
	docker compose exec backend pytest
