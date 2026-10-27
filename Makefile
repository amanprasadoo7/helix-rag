COMPOSE_FILE := infra/docker-compose.yml
ENV_FILE := $(if $(wildcard .env),--env-file .env,)
COMPOSE := docker compose -f $(COMPOSE_FILE) $(ENV_FILE)

.PHONY: sync dev test test-integration lint fmt ci checklist docs corpus corpus-clean parse parse-sample classify classify-sample compare up down reset ps logs ready tools tools-down

PARSERS ?= native,docling,unstructured
STRATEGY ?= fast

sync:
	uv sync

dev:
	uv run python -m apps.api.dev

test:
	uv run pytest -m "not integration"

test-integration:
	uv run pytest -m integration

lint:
	uv run ruff check .
	uv run mypy packages/helix apps

fmt:
	uv run ruff format .
	uv run ruff check --fix .

checklist:
	uv run python scripts/checklist.py

docs:
	uv run python scripts/build_theory.py

corpus:
	uv run python scripts/fetch_corpus.py

corpus-clean:
	uv run python scripts/prune_corpus.py

parse:
	uv run python scripts/parse_corpus.py

parse-sample:
	uv run python scripts/parse_corpus.py --limit 5 --verbose

classify:
	uv run python scripts/classify_corpus.py

classify-sample:
	uv run python scripts/classify_corpus.py --limit 5 --verbose

compare:
	@test -n "$(FILE)" || (echo "usage: make compare FILE=path/to/file [OUT=dir] [PARSERS=native,docling,unstructured] [STRATEGY=fast]"; exit 1)
	uv run --extra parsers python scripts/compare_parsers.py "$(FILE)" \
		--parsers "$(PARSERS)" \
		--unstructured-strategy "$(STRATEGY)" \
		$(if $(OUT),--out "$(OUT)",)

ci: lint test

up:
	$(COMPOSE) up -d --wait --wait-timeout 120

down:
	$(COMPOSE) down

reset:
	$(COMPOSE) down -v

ps:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f --tail=100

tools:
	$(COMPOSE) --profile tools up -d --wait adminer redisinsight

tools-down:
	$(COMPOSE) --profile tools stop adminer redisinsight

ready:
	uv run python -c "import sys, httpx; from helix.config import get_settings; s=get_settings(); r=httpx.get(f'http://{s.api_host}:{s.api_port}/health/ready', timeout=5); print(r.status_code, r.text); sys.exit(0 if r.is_success else 1)"
