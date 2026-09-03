.PHONY: install test check demo agent-demo model-check dev

install:
	cd backend && uv sync --all-groups

test:
	cd backend && uv run pytest --cov=ad_rca --cov-report=term-missing

check:
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run pyright

demo:
	cd backend && uv run profitlens investigate ../fixtures/demo/pricing_error.json --format json

agent-demo:
	cd backend && uv run profitlens agent ../fixtures/demo/pricing_error.json --model fake --format json

model-check:
	cd backend && uv run profitlens model-check

dev:
	cd backend && uv run profitlens serve
