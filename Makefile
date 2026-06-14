SHELL := /bin/bash
.ONESHELL:
.DEFAULT_GOAL := help

PYTHON ?= python
AGENTPACK ?= PYTHONPATH=src $(PYTHON) -m agentpack.cli

.PHONY: help context context-thread test lint npm-test docs-check build benchmark benchmark-publish release-docs release-fast release verify-wheel clean-build

help: ## Show available developer commands.
	@awk 'BEGIN {FS = ":.*##"; printf "\nAgentPack developer commands:\n\n"} /^[a-zA-Z0-9_-]+:.*##/ {printf "  %-18s %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@printf "\nExamples:\n"
	@printf "  make release-docs       # docs/plugin-only release gate\n"
	@printf "  make release-fast       # quick local gate while iterating\n"
	@printf "  make release            # full release-check, including benchmark gate\n"
	@printf "  make verify-wheel       # build wheel, install in temp venv, run release benchmark\n"
	@printf "  THREAD=codex-local make context-thread\n\n"

context: ## Pack context from .agentpack/task.md using legacy global mode.
	$(AGENTPACK) pack --task auto

context-thread: ## Pack scoped context with THREAD=<id> or AGENTPACK_THREAD_ID + --thread auto.
	@if [ -n "$${THREAD:-}" ]; then \
		$(AGENTPACK) pack --task auto --thread "$$THREAD"; \
	else \
		$(AGENTPACK) pack --task auto --thread auto; \
	fi

test: ## Run the full Python test suite.
	pytest -q

lint: ## Run ruff over source and tests.
	$(PYTHON) -m ruff check src tests

npm-test: ## Run npm launcher/version tests.
	node npm/test/version-sync.test.js
	node npm/test/launcher.test.js

docs-check: ## Check markdown links, README size, and whitespace.
	pytest tests/test_docs_links.py -q
	git diff --check

build: ## Build wheel and sdist into dist/.
	$(PYTHON) -m build

benchmark: ## Run public benchmark gate without writing result markdown.
	$(AGENTPACK) benchmark --release-gate --no-public-table

benchmark-publish: ## Run public benchmark gate and write benchmarks/results/*-public.md.
	$(AGENTPACK) benchmark --release-gate

release-fast: ## Fast local release gate: changelog, version sync, pytest, npm tests.
	$(AGENTPACK) release-check --skip-benchmark --skip-build

release-docs: ## Fast docs/plugin release gate: focused tests, no build, no benchmark.
	$(AGENTPACK) release-check --profile docs

release: ## Full release gate: changelog, version sync, pytest, npm tests, build, benchmark.
	$(AGENTPACK) release-check

verify-wheel: build ## Install latest built wheel in a temp venv and run release benchmark gate.
	tmpdir="$$(mktemp -d)"
	trap 'rm -rf "$$tmpdir"' EXIT
	"$(PYTHON)" -m venv "$$tmpdir/venv"
	wheel="$$(ls -t dist/agentpack_cli-*.whl | head -1)"
	"$$tmpdir/venv/bin/pip" install "$$wheel"
	"$$tmpdir/venv/bin/agentpack" benchmark --release-gate --no-public-table

clean-build: ## Remove local build outputs.
	rm -rf build dist *.egg-info src/*.egg-info
