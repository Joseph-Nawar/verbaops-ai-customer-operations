UV ?= uv

.PHONY: sync lint format-check typecheck test check dev down migrate commerce-migrate commerce-seed commerce-acceptance commerce-client-contract llm-gateway-contract rag-unit-contract rag-contract rag-evaluation-contract agent-acceptance postgres-contract postgres-concurrency postgres-critical-race knowledge-contract commerce-contract-check commerce-contract-update web-check web-smoke eval-corpus-check rag-eval-corpus-check eval-agent eval-agent-live eval-agent-finalize eval-agent-finalization-rehearsal eval-agent-rescore eval-compare

sync:
	$(UV) sync

lint:
	$(UV) run ruff check .

format-check:
	$(UV) run ruff format --check .

typecheck:
	$(UV) run mypy src tests scripts

test:
	$(UV) run pytest -m "not postgres and not commerce_acceptance and not commerce_client_contract and not llm_gateway_contract and not agent_acceptance"

check:
	$(MAKE) sync
	$(MAKE) lint
	$(MAKE) format-check
	$(MAKE) typecheck
	$(MAKE) test
	$(UV) run pytest -m "not postgres and not commerce_acceptance and not commerce_client_contract and not llm_gateway_contract and not agent_acceptance" --cov=verbaops --cov=novacommerce --cov-report=term-missing
	$(UV) run pre-commit run --all-files
	git diff --check

dev:
	$(UV) run python scripts/bootstrap_dev_env.py
	docker compose up --build

down:
	docker compose down

migrate:
	$(UV) run python scripts/bootstrap_dev_env.py
	docker compose up -d --wait postgres redis
	docker compose run --rm migrate

commerce-migrate:
	$(UV) run python scripts/bootstrap_dev_env.py
	docker compose up -d --wait commerce-postgres
	docker compose run --rm commerce-migrate

commerce-seed:
	$(UV) run python scripts/bootstrap_dev_env.py
	docker compose --profile seed run --build --rm commerce-seed

commerce-acceptance:
	$(UV) run python -m scripts.run_commerce_acceptance

commerce-client-contract:
	$(UV) run python -m scripts.run_commerce_client_contract

llm-gateway-contract:
	$(UV) run python -m scripts.run_llm_gateway_contract

rag-unit-contract:
	$(UV) run pytest tests/retrieval tests/knowledge/test_embeddings.py -m "contract" -q

rag-contract:
	$(UV) run python scripts/require_test_database.py
	$(UV) run alembic upgrade 0005_retrieval_grounding_v1
	$(UV) run pytest tests/postgres/m5b -m "postgres and contract" -q
	$(UV) run pytest tests/retrieval tests/agent/test_retrieval_graph.py tests/agent/test_grounding_security.py tests/api/test_conversations_m5b.py -m "not postgres and not llm_gateway_contract and not agent_acceptance" -q

rag-evaluation-contract:
	$(UV) run python scripts/check_rag_eval_corpus.py
	$(UV) run pytest tests/evaluation -k "rag_" -q

rag-eval-corpus-check:
	$(UV) run python scripts/check_rag_eval_corpus.py

agent-acceptance:
	$(UV) run python -m scripts.run_agent_acceptance

postgres-contract:
	$(UV) run python scripts/require_test_database.py
	$(UV) run pytest -m "postgres and contract"

postgres-concurrency:
	$(UV) run python scripts/require_test_database.py
	$(UV) run pytest -m "postgres and concurrency"

postgres-critical-race:
	$(UV) run python scripts/require_test_database.py
	$(UV) run pytest -m "postgres and concurrency and critical_race"

knowledge-contract:
	$(UV) run alembic upgrade 0004_knowledge_rag_v1
	$(UV) run python scripts/ingest_knowledge_corpus.py --check
	$(UV) run pytest tests/knowledge tests/postgres/m5a tests/api/test_knowledge_admin.py tests/worker/test_knowledge_tasks.py -m "not llm_gateway_contract" -q

commerce-contract-check:
	$(UV) run python scripts/normalize_openapi.py --check contracts/novacommerce-openapi.json

commerce-contract-update:
	$(UV) run python scripts/normalize_openapi.py --update contracts/novacommerce-openapi.json

web-check:
	corepack pnpm --dir apps/web install --frozen-lockfile
	corepack pnpm --dir apps/web lint
	corepack pnpm --dir apps/web typecheck
	corepack pnpm --dir apps/web test
	corepack pnpm --dir apps/web build

web-smoke:
	corepack pnpm --dir apps/web smoke

eval-corpus-check:
	$(UV) run python scripts/check_eval_corpus.py

eval-agent:
	$(UV) run python scripts/run_agent_eval.py --adapter deterministic

eval-agent-live:
	$(UV) run python scripts/run_agent_eval_live.py

eval-agent-finalize:
	$(UV) run python scripts/run_agent_eval_live.py --finalize --run-id "$(RUN_ID)"

eval-agent-finalization-rehearsal:
	$(UV) run python scripts/rehearse_agent_eval_finalization.py

eval-agent-rescore:
	$(UV) run python scripts/rescore_agent_eval.py --run-id "$(RUN_ID)" --evaluator-sha "$(EVALUATOR_SHA)"

eval-compare:
	$(UV) run python scripts/compare_agent_evals.py --baseline "$(BASELINE)" --candidate "$(CANDIDATE)"
