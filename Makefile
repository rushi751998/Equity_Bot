.PHONY: install test lint typecheck
install:
	pip install -e ".[dev]"
test:
	pytest
lint:
	ruff check src tests
typecheck:
	mypy src

start:
	tfalgo server

.PHONY: start-local
start-local:
	.venv/Scripts/uvicorn tfalgo.web.server:create_app --factory --app-dir src --host 127.0.0.1 --port 5000 --reload --reload-dir src   