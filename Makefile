.PHONY: install lint format typecheck test test-postgres run migrate check openspec

install:
	uv sync --frozen

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

typecheck:
	uv run mypy

test:
	uv run pytest --cov --cov-report=term-missing

test-postgres:
	PROMPTLAB_TEST_DATABASE_URL=$${PROMPTLAB_TEST_DATABASE_URL:-postgresql+asyncpg://promptlab:promptlab@localhost:5432/promptlab_test} uv run pytest

openspec:
	npx --yes @fission-ai/openspec@1.14.3 validate --all --strict

run:
	uv run promptlab serve --reload

migrate:
	uv run promptlab migrate

check: lint typecheck test openspec
