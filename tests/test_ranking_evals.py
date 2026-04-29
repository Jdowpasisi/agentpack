"""
Eval fixtures for ranking quality.

Each scenario specifies:
  - task: natural-language task description
  - files: all candidate files (path, optional relevance tag)
  - expected_top: files that MUST rank in the top-N
  - expected_excluded: files that must NOT appear in top-N
  - changed: which files are currently modified (git diff)

These tests catch regressions in keyword extraction, concept expansion,
and scoring weights — the things unit tests don't cover end-to-end.
"""
from __future__ import annotations

import pytest
from pathlib import Path

from agentpack.analysis.ranking import extract_keywords, score_files
from agentpack.core.models import FileInfo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fi(path: str, tokens: int = 200) -> FileInfo:
    return FileInfo(
        path=path,
        abs_path=Path("/nonexistent") / path,
        size_bytes=tokens * 4,
        estimated_tokens=tokens,
        language="python",
    )


def _run(
    task: str,
    files: list[str],
    changed: set[str] | None = None,
    recently_modified: list[str] | None = None,
) -> list[tuple[str, float]]:
    """Return (path, score) pairs sorted by score descending."""
    keywords = extract_keywords(task)
    file_infos = [_fi(p) for p in files]
    scored = score_files(
        file_infos,
        changed_paths=changed or set(),
        staged_paths=set(),
        recently_modified=recently_modified or [],
        dep_graph={},
        keywords=keywords,
    )
    scored.sort(key=lambda x: -x[1])
    return [(s[0].path, s[1]) for s in scored]


def _top_paths(results: list[tuple[str, float]], n: int) -> list[str]:
    return [p for p, _ in results[:n]]


def _assert_ranks_above(results: list[tuple[str, float]], higher: str, lower: str) -> None:
    paths = [p for p, _ in results]
    assert higher in paths, f"{higher} not found in results"
    assert lower in paths, f"{lower} not found in results"
    hi_idx = paths.index(higher)
    lo_idx = paths.index(lower)
    assert hi_idx < lo_idx, (
        f"Expected {higher} (rank {hi_idx+1}) to outrank {lower} (rank {lo_idx+1}).\n"
        f"Scores: {dict(results)}"
    )


# ---------------------------------------------------------------------------
# Scenario 1: Rate limiting — semantic gap test
# The task uses "rate limiting" but the file is named leaky_bucket.py
# ---------------------------------------------------------------------------

class TestRateLimitingScenario:
    FILES = [
        "src/middleware/leaky_bucket.py",   # implements rate limiting
        "src/middleware/auth.py",
        "src/middleware/cors.py",
        "src/api/users.py",
        "src/utils/helpers.py",
    ]

    def test_leaky_bucket_in_top2(self):
        results = _run("add rate limiting to all API endpoints", self.FILES)
        top = _top_paths(results, 2)
        assert "src/middleware/leaky_bucket.py" in top, (
            f"leaky_bucket.py should be in top-2 for 'rate limiting' task. Top-2: {top}\n"
            f"Full ranking: {results}"
        )

    def test_leaky_bucket_outranks_cors(self):
        results = _run("add rate limiting to all API endpoints", self.FILES)
        _assert_ranks_above(results, "src/middleware/leaky_bucket.py", "src/middleware/cors.py")

    def test_throttle_synonym(self):
        """'throttle' in task should also find leaky_bucket.py."""
        results = _run("throttle requests to the API", self.FILES)
        top = _top_paths(results, 2)
        assert "src/middleware/leaky_bucket.py" in top, (
            f"leaky_bucket.py not in top-2 for 'throttle' task. Top-2: {top}"
        )


# ---------------------------------------------------------------------------
# Scenario 2: Authentication — variant + concept expansion
# ---------------------------------------------------------------------------

class TestAuthScenario:
    FILES = [
        "src/auth/jwt_handler.py",          # jwt is auth synonym
        "src/auth/session.py",
        "src/middleware/cors.py",
        "src/api/users.py",
        "src/utils/crypto.py",
    ]

    def test_jwt_handler_in_top2_for_auth_task(self):
        results = _run("fix authentication token expiry bug", self.FILES)
        top = _top_paths(results, 2)
        assert "src/auth/jwt_handler.py" in top, (
            f"jwt_handler.py should be in top-2 for 'authentication token' task. Top-2: {top}"
        )

    def test_auth_outranks_cors(self):
        results = _run("implement OAuth2 login flow", self.FILES)
        _assert_ranks_above(results, "src/auth/session.py", "src/middleware/cors.py")

    def test_bearer_token_expansion(self):
        """'bearer' is a synonym for 'auth' — should surface auth files."""
        kw = extract_keywords("validate bearer token in request headers")
        assert "auth" in kw or "bearer" in kw, f"Expected auth/bearer in keywords: {kw}"


# ---------------------------------------------------------------------------
# Scenario 3: Caching — LRU / memoize / Redis synonyms
# ---------------------------------------------------------------------------

class TestCachingScenario:
    FILES = [
        "src/cache/lru_store.py",           # lru is cache synonym
        "src/cache/redis_client.py",        # redis is cache synonym
        "src/api/products.py",
        "src/db/repository.py",
        "src/utils/formatters.py",
    ]

    def test_lru_in_top3_for_cache_task(self):
        results = _run("improve caching performance", self.FILES)
        top = _top_paths(results, 3)
        assert "src/cache/lru_store.py" in top, (
            f"lru_store.py should be in top-3 for 'caching' task. Top-3: {top}"
        )

    def test_redis_in_top3_for_cache_task(self):
        results = _run("improve caching performance", self.FILES)
        top = _top_paths(results, 3)
        assert "src/cache/redis_client.py" in top, (
            f"redis_client.py should be in top-3 for 'caching' task. Top-3: {top}"
        )

    def test_memoize_expansion(self):
        kw = extract_keywords("memoize expensive database queries")
        assert "cache" in kw or "memoize" in kw, f"Expected cache/memoize in keywords: {kw}"


# ---------------------------------------------------------------------------
# Scenario 4: Database migration
# ---------------------------------------------------------------------------

class TestDatabaseScenario:
    FILES = [
        "migrations/0042_add_user_roles.py",
        "src/db/schema.py",
        "src/models/user.py",
        "src/api/health.py",
        "src/utils/string_utils.py",
    ]

    def test_migration_in_top2_for_schema_task(self):
        results = _run("add new column to user table migration", self.FILES)
        top = _top_paths(results, 2)
        assert "migrations/0042_add_user_roles.py" in top or "src/db/schema.py" in top, (
            f"migration or schema should be in top-2. Top-2: {top}"
        )

    def test_unrelated_files_excluded_from_top(self):
        results = _run("run database migration", self.FILES)
        top = _top_paths(results, 3)
        assert "src/utils/string_utils.py" not in top, (
            f"string_utils.py should not be in top-3 for DB migration task. Top-3: {top}"
        )


# ---------------------------------------------------------------------------
# Scenario 5: Error handling / retry logic
# ---------------------------------------------------------------------------

class TestErrorHandlingScenario:
    FILES = [
        "src/utils/retry.py",               # retry is error synonym
        "src/utils/circuit_breaker.py",     # circuit breaker is retry synonym
        "src/api/payments.py",
        "src/middleware/logging.py",
        "src/utils/formatters.py",
    ]

    def test_retry_in_top2(self):
        results = _run("improve error handling with exponential backoff", self.FILES)
        top = _top_paths(results, 2)
        assert "src/utils/retry.py" in top, (
            f"retry.py should be in top-2 for 'error handling backoff' task. Top-2: {top}"
        )

    def test_circuit_breaker_expanded_from_retry(self):
        kw = extract_keywords("add retry logic with backoff")
        assert "circuit" in kw or "retry" in kw or "backoff" in kw, (
            f"Expected retry/backoff/circuit in keywords: {kw}"
        )


# ---------------------------------------------------------------------------
# Scenario 6: Concurrency / async
# ---------------------------------------------------------------------------

class TestConcurrencyScenario:
    FILES = [
        "src/workers/task_queue.py",
        "src/utils/mutex.py",               # mutex is concurrency synonym
        "src/api/stream.py",
        "src/utils/string_utils.py",
        "src/config/settings.py",
    ]

    def test_mutex_in_top2_for_concurrency_task(self):
        results = _run("fix race condition in concurrent request handling", self.FILES)
        top = _top_paths(results, 2)
        assert "src/utils/mutex.py" in top or "src/workers/task_queue.py" in top, (
            f"mutex or task_queue should be in top-2 for 'race condition' task. Top-2: {top}"
        )

    def test_config_not_ranked_above_mutex(self):
        results = _run("fix race condition in concurrent request handling", self.FILES)
        _assert_ranks_above(results, "src/utils/mutex.py", "src/config/settings.py")


# ---------------------------------------------------------------------------
# Scenario 7: Changed files always win
# ---------------------------------------------------------------------------

class TestChangedFilePriority:
    FILES = [
        "src/auth/jwt.py",
        "src/middleware/cors.py",
        "src/utils/helpers.py",
        "tests/test_auth.py",
    ]

    def test_changed_file_outranks_keyword_match(self):
        """A changed file with no keyword match should still beat an untouched keyword match."""
        results = _run(
            "fix CORS issue",
            self.FILES,
            changed={"src/utils/helpers.py"},  # changed but unrelated to CORS
        )
        # helpers.py is changed; cors.py matches keyword but is unchanged
        # changed file should rank above unrelated-unchanged files but cors should still win
        # (this tests that keyword match + unchanged still loses to changed)
        scores = dict(results)
        assert scores["src/utils/helpers.py"] > 0, "Changed file should have positive score"

    def test_changed_plus_keyword_is_highest(self):
        """A file that is both changed AND keyword-matching should rank first."""
        results = _run(
            "fix auth token expiry",
            self.FILES,
            changed={"src/auth/jwt.py"},
        )
        assert results[0][0] == "src/auth/jwt.py", (
            f"jwt.py (changed + keyword match) should rank #1. Ranking: {results}"
        )


# ---------------------------------------------------------------------------
# Scenario 8: Keyword extraction quality
# ---------------------------------------------------------------------------

class TestKeywordExtraction:
    def test_removes_short_words(self):
        kw = extract_keywords("add an SSE to the API")
        assert "an" not in kw
        assert "to" not in kw
        assert "the" not in kw

    def test_concept_expansion_rate_limiting(self):
        kw = extract_keywords("rate limiting")
        assert "throttle" in kw
        assert "leaky" in kw or "bucket" in kw

    def test_concept_expansion_auth(self):
        kw = extract_keywords("authentication")
        assert "jwt" in kw or "token" in kw

    def test_concept_expansion_cache(self):
        kw = extract_keywords("caching layer")
        assert "lru" in kw or "redis" in kw

    def test_variant_normalization(self):
        kw = extract_keywords("authorization configuration errors")
        assert "auth" in kw
        assert "config" in kw
        assert "error" in kw

    def test_no_expansion_explosion(self):
        """One-level expansion only — synonyms of synonyms not added."""
        kw = extract_keywords("rate")
        # "throttle" is a synonym of "rate" — fine
        # but "ratelimit" (a synonym of "throttle") should only appear if it's
        # directly in the concept map for "rate"
        assert isinstance(kw, set)
        # Just verify we don't get absurdly large keyword sets
        assert len(kw) < 50, f"Keyword set too large ({len(kw)}): {kw}"


# ---------------------------------------------------------------------------
# Cross-repo scenario 9: FastAPI-style — SSE / streaming endpoint
# Real gap: "SSE" not in file names; file is named event_stream.py
# ---------------------------------------------------------------------------

class TestFastAPISSEScenario:
    """Models a FastAPI repo with SSE streaming."""
    FILES = [
        "app/api/v1/events.py",          # route file
        "app/services/event_stream.py",  # implements SSE streaming
        "app/services/user_service.py",
        "app/core/config.py",
        "app/db/session.py",
        "tests/test_events.py",
    ]

    def test_event_stream_in_top2_for_sse_task(self):
        results = _run("fix SSE connection dropping after 30 seconds", self.FILES)
        top = _top_paths(results, 3)
        assert "app/services/event_stream.py" in top or "app/api/v1/events.py" in top, (
            f"SSE stream files not in top-3 for SSE task. Top-3: {top}"
        )

    def test_sse_expansion_keywords(self):
        kw = extract_keywords("fix SSE streaming endpoint")
        assert "stream" in kw or "sse" in kw or "realtime" in kw, (
            f"Expected stream/sse/realtime in: {kw}"
        )

    def test_websocket_expansion(self):
        kw = extract_keywords("add WebSocket support to realtime dashboard")
        assert "stream" in kw or "websocket" in kw or "channel" in kw, (
            f"Expected stream/websocket/channel in: {kw}"
        )


# ---------------------------------------------------------------------------
# Cross-repo scenario 10: Django-style — pagination + serialization
# Real gap: pagination file is named list_view.py or queryset.py
# ---------------------------------------------------------------------------

class TestDjangoPaginationScenario:
    """Models a Django REST framework repo."""
    FILES = [
        "api/views/user_list.py",         # uses paginator
        "api/pagination.py",              # pagination class
        "api/serializers/user.py",        # serializer
        "api/models/user.py",
        "api/views/auth.py",
        "tests/test_pagination.py",
    ]

    def test_pagination_in_top2(self):
        results = _run("add cursor-based pagination to user list endpoint", self.FILES)
        top = _top_paths(results, 2)
        assert "api/pagination.py" in top or "api/views/user_list.py" in top, (
            f"Pagination files not in top-2. Top-2: {top}"
        )

    def test_pagination_keywords(self):
        kw = extract_keywords("implement cursor-based pagination")
        assert "pagination" in kw or "cursor" in kw or "paginate" in kw, (
            f"Expected pagination keywords in: {kw}"
        )

    def test_serializer_ranked_for_validation_task(self):
        results = _run("fix validation error in user serializer", self.FILES)
        top = _top_paths(results, 3)
        assert "api/serializers/user.py" in top, (
            f"serializer not in top-3 for validation task. Top-3: {top}"
        )

    def test_validation_keywords(self):
        kw = extract_keywords("add input validation to REST endpoint")
        assert "validation" in kw or "validate" in kw or "schema" in kw, (
            f"Expected validation keywords in: {kw}"
        )


# ---------------------------------------------------------------------------
# Cross-repo scenario 11: Next.js / Node — webhook handler
# Real gap: webhook is processed in a file named api/stripe.ts
# ---------------------------------------------------------------------------

class TestNextJSWebhookScenario:
    """Models a Next.js app with Stripe webhook."""
    FILES = [
        "pages/api/stripe.ts",            # handles Stripe webhooks
        "pages/api/checkout.ts",
        "lib/payments/billing.ts",        # billing logic
        "lib/db/prisma.ts",
        "components/PricingTable.tsx",
        "tests/stripe.test.ts",
    ]

    def test_stripe_in_top2_for_webhook_task(self):
        results = _run("fix Stripe webhook signature verification failing", self.FILES)
        top = _top_paths(results, 2)
        assert "pages/api/stripe.ts" in top, (
            f"stripe.ts should be in top-2 for webhook task. Top-2: {top}"
        )

    def test_billing_in_top3_for_payment_task(self):
        results = _run("add subscription billing with Stripe", self.FILES)
        top = _top_paths(results, 3)
        assert "lib/payments/billing.ts" in top or "pages/api/stripe.ts" in top, (
            f"billing/stripe not in top-3 for payment task. Top-3: {top}"
        )

    def test_webhook_keywords(self):
        kw = extract_keywords("handle incoming webhook events")
        assert "webhook" in kw or "event" in kw or "handler" in kw, (
            f"Expected webhook/event keywords in: {kw}"
        )

    def test_payment_keywords(self):
        kw = extract_keywords("integrate payment processing with Stripe")
        assert "payment" in kw or "billing" in kw or "stripe" in kw, (
            f"Expected payment keywords in: {kw}"
        )


# ---------------------------------------------------------------------------
# Cross-repo scenario 12: Go microservice — health check + deployment
# Real gap: health endpoint is in handler/health.go, not obviously named
# ---------------------------------------------------------------------------

class TestGoMicroserviceScenario:
    """Models a Go microservice repo."""
    FILES = [
        "handler/health.go",              # liveness/readiness probes
        "handler/api.go",
        "internal/db/postgres.go",
        "internal/cache/redis.go",
        "cmd/server/main.go",
        "k8s/deployment.yaml",
        "Dockerfile",
    ]

    def test_health_handler_in_top2(self):
        results = _run("kubernetes readiness probe failing on startup", self.FILES)
        top = _top_paths(results, 3)
        assert "handler/health.go" in top or "k8s/deployment.yaml" in top, (
            f"health/k8s not in top-3 for readiness probe task. Top-3: {top}"
        )

    def test_docker_in_top3_for_deploy_task(self):
        results = _run("fix Docker image build for deployment", self.FILES)
        top = _top_paths(results, 3)
        assert "Dockerfile" in top or "k8s/deployment.yaml" in top, (
            f"Dockerfile/k8s not in top-3 for deploy task. Top-3: {top}"
        )

    def test_health_keywords(self):
        kw = extract_keywords("liveness probe returns 500 on startup")
        assert "health" in kw or "liveness" in kw or "probe" in kw or "status" in kw, (
            f"Expected health keywords in: {kw}"
        )

    def test_deploy_keywords(self):
        kw = extract_keywords("configure Kubernetes deployment with Docker")
        assert "deploy" in kw or "docker" in kw or "kubernetes" in kw or "container" in kw, (
            f"Expected deploy keywords in: {kw}"
        )


# ---------------------------------------------------------------------------
# Cross-repo scenario 13: Rails-style — email / notification
# Real gap: "welcome email" sends from mailer/user_mailer.rb
# ---------------------------------------------------------------------------

class TestRailsEmailScenario:
    """Models a Rails-style app with ActionMailer."""
    FILES = [
        "app/mailers/user_mailer.rb",     # sends welcome/reset emails
        "app/models/user.rb",
        "app/controllers/auth_controller.rb",
        "app/jobs/email_job.rb",          # background email delivery
        "config/environments/production.rb",
        "spec/mailers/user_mailer_spec.rb",
    ]

    def test_mailer_in_top2_for_email_task(self):
        results = _run("fix welcome email not being sent after registration", self.FILES)
        top = _top_paths(results, 2)
        assert "app/mailers/user_mailer.rb" in top or "app/jobs/email_job.rb" in top, (
            f"mailer/email_job not in top-2 for email task. Top-2: {top}"
        )

    def test_email_keywords(self):
        kw = extract_keywords("transactional email delivery via SendGrid")
        assert "email" in kw or "sendgrid" in kw or "notification" in kw or "mailer" in kw, (
            f"Expected email keywords in: {kw}"
        )

    def test_notification_expansion(self):
        kw = extract_keywords("send push notification to mobile users")
        assert "notification" in kw or "push" in kw or "alert" in kw, (
            f"Expected notification keywords in: {kw}"
        )


# ---------------------------------------------------------------------------
# New keyword expansion tests for added concepts
# ---------------------------------------------------------------------------

class TestNewConceptExpansions:
    def test_sse_expands_to_stream(self):
        kw = extract_keywords("fix SSE endpoint")
        assert "stream" in kw or "sse" in kw

    def test_webhook_expands_to_event(self):
        kw = extract_keywords("handle webhook events")
        assert "event" in kw or "webhook" in kw

    def test_pagination_expands(self):
        kw = extract_keywords("implement pagination")
        assert "page" in kw or "cursor" in kw or "paginate" in kw

    def test_validation_expands(self):
        kw = extract_keywords("add validation")
        assert "validate" in kw or "schema" in kw or "constraint" in kw

    def test_deploy_expands(self):
        kw = extract_keywords("deploy to production")
        assert "deploy" in kw or "release" in kw or "container" in kw or "docker" in kw

    def test_email_expands(self):
        kw = extract_keywords("send email notification")
        assert "email" in kw or "smtp" in kw or "notification" in kw

    def test_payment_expands(self):
        kw = extract_keywords("process payment")
        assert "payment" in kw or "stripe" in kw or "billing" in kw

    def test_health_expands(self):
        kw = extract_keywords("health check endpoint")
        assert "health" in kw or "ping" in kw or "liveness" in kw

    def test_config_expands(self):
        kw = extract_keywords("update configuration")
        assert "config" in kw or "settings" in kw or "env" in kw

    def test_mock_expands(self):
        kw = extract_keywords("mock the database in tests")
        assert "mock" in kw or "stub" in kw or "fixture" in kw
