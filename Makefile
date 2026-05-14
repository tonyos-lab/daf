.PHONY: test-unit test-integration test-adversarial test-all services-up services-down lint format

test-unit:
	pytest tests/unit/ -v --tb=short

test-integration:
	pytest tests/integration/ -v --tb=short

test-adversarial:
	pytest tests/adversarial/ -v --tb=short -x

test-all:
	pytest tests/ -v --tb=short

test-coverage:
	pytest tests/ --cov=daf --cov-report=html --cov-report=term-missing

services-up:
	docker compose up -d
	@echo "Services started. Check status with: make services-status"

services-down:
	docker compose down

services-reset:
	docker compose down -v
	docker compose up -d

services-status:
	docker compose ps

lint:
	ruff check .

format:
	ruff format .

jupyter:
	jupyter lab experiments/

cost-today:
	python scripts/cost_report.py --period today

cost-month:
	python scripts/cost_report.py --period month
