api-up:
	docker compose up --build -d

run:
	uv run main.py

test:
	uv run pytest

migration-dry-run:
	uv run python -m scripts.migrate_users


