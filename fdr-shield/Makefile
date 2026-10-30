up:
	docker compose up --build
seed:
	docker compose exec backend python -m scripts.seed
migrate:
	docker compose exec backend alembic upgrade head
backfill-workflows:
	docker compose exec backend python -m scripts.backfill_workflows
test:
	docker compose exec backend pytest
